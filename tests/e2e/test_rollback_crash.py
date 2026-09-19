"""H-023 (b): kill -9 mid-rollback, resume completes with no double-apply.

Real subprocess killed with Popen.kill(), real Postgres, real CRM over HTTP.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from hyperion.executor import executor, rollback_exec

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]


def _running_steps(conn, rollback_id) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM rollback_steps WHERE rollback_id = %s "
        "AND status = 'running'",
        (rollback_id,),
    ).fetchone()
    return int(row[0])


def _step_states(conn, rollback_id) -> dict:
    rows = conn.execute(
        """SELECT s.call_id, s.status, s.outcome FROM rollback_steps s
           WHERE s.rollback_id = %s""",
        (rollback_id,),
    ).fetchall()
    return {str(call_id): (status, outcome) for call_id, status, outcome in rows}


def test_kill_mid_rollback_then_resume(env, crm_base_url):
    conn, run_id, clients, specs = (env["conn"], env["run_id"],
                                    env["clients"], env["specs"])
    lead = executor.execute(conn, run_id, "crm", "leads.create",
                            {"name": "Crash"}, specs=specs, clients=clients)
    deal = executor.execute(
        conn, run_id, "crm", "deals.create",
        {"lead_id": lead["produced"]["lead_id"], "title": "D"},
        specs=specs, clients=clients, declared_deps=[lead["call_id"]])
    note = executor.execute(
        conn, run_id, "crm", "notes.add",
        {"deal_id": deal["produced"]["deal_id"], "body": "n"},
        specs=specs, clients=clients, declared_deps=[deal["call_id"]])
    child_env = dict(os.environ)
    child_env["PYTHONPATH"] = os.pathsep.join(
        [str(REPO_ROOT / "src"), child_env.get("PYTHONPATH", "")])
    child_env["ROLLBACK_HOOK_SLEEP"] = "15"

    proc = subprocess.Popen(
        [sys.executable, str(REPO_ROOT / "tests" / "e2e" / "rollback_worker.py"),
         "--run", run_id, "--targets",
         ",".join([lead["call_id"]]),
         "--crm", crm_base_url],
        env=child_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, cwd=str(REPO_ROOT),
    )
    try:
        assert proc.stdout is not None
        line = proc.stdout.readline()
        assert line, f"worker died early: {proc.stderr.read()[-2000:]}"
        rollback_id = json.loads(line)["rollback_id"]
        deadline = time.time() + 60
        while _running_steps(conn, rollback_id) == 0:
            assert proc.poll() is None, (
                f"worker exited early: {proc.stderr.read()[-2000:]}")
            assert time.time() < deadline, "no step reached running"
            time.sleep(0.5)
        proc.kill()  # portable SIGKILL equivalent (TerminateProcess on Windows)
        proc.wait(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=30)

    applied: list[str] = []

    def counting_hook(step, call, spec):
        applied.append(step["call_id"])

    out = rollback_exec.resume(conn, rollback_id, clients, specs,
                               counting_hook)
    assert out["status"] == "completed"
    # Every inverse applied exactly once: the killed run sent none (it died
    # in the pre-inverse sleep), the resume sent each one.
    assert sorted(applied) == sorted(
        [lead["call_id"], deal["call_id"], note["call_id"]])
    states = _step_states(conn, rollback_id)
    assert set(states) == {lead["call_id"], deal["call_id"], note["call_id"]}
    assert all(s == "done" for s, _ in states.values())

    code, _ = clients["crm"].request(
        "GET", "/leads/{lead_id}", {"lead_id": lead["produced"]["lead_id"]})
    assert code == 410
    code, _ = clients["crm"].request(
        "GET", "/notes/{note_id}", {"note_id": note["produced"]["note_id"]})
    assert code == 404
