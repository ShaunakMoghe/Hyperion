"""M9: policy gates end to end (real Postgres + live CRM, no mocks).

Gateway -> policy deny/hold, approve flow, run provenance stamp, audit
export shape, resume-policy refusal, CLI plumbing, and fail-fast startup
on a bad policy file.
"""

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from hyperion import cli as cli_mod
from hyperion.executor import approvals, executor
from hyperion.executor import policy as policy_mod
from hyperion.ledger import export as audit_export
from hyperion.ledger import store
from hyperion.mcp_gateway.proxy import Gateway, check_resume_policy

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]

MAP = {"tools": {
    "crm_create_lead": {"system": "crm", "operation": "leads.create"},
    "crm_delete_lead": {"system": "crm", "operation": "leads.delete"},
}, "unknown": "deny"}


def _call(tool: str, args: dict, request_id: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "method": "tools/call",
            "params": {"name": tool, "arguments": args}}


def _policy(text: str):
    parsed, error = policy_mod.loads_policy(text)
    assert error is None, error
    return parsed


def test_gateway_denies_per_policy_and_records_reason(env):
    gw = Gateway(
        MAP, env["conn"], env["run_id"], env["specs"], env["clients"],
        policy=_policy(
            "default: allow\nrules:\n"
            "  - match: {system: crm, operation: leads.delete}\n"
            "    effect: deny\n"))
    resp = gw.handle_message(
        _call("crm_delete_lead", {"lead_id": "whatever"}))
    assert resp["result"]["isError"] is True
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["status"] == "denied"
    row = store.get_call(env["conn"], payload["call_id"])
    assert row["status"] == "blocked"
    assert "policy denied" in (row["decision_reason"] or "")


def test_gateway_hold_approve_flow_with_pending_list(env):
    gw = Gateway(
        MAP, env["conn"], env["run_id"], env["specs"], env["clients"],
        policy=_policy(
            "default: allow\nrules:\n"
            "  - match: {system: crm, operation: leads.create}\n"
            "    effect: require_approval\n"))
    resp = gw.handle_message(_call("crm_create_lead", {"name": "HeldLead"}))
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["result"] == approvals.PENDING

    pending = approvals.list_pending(env["conn"], env["run_id"])
    assert [p["call_id"] for p in pending] == [payload["call_id"]]
    assert pending[0]["operation"] == "leads.create"
    assert "require_approval" in (pending[0]["reason"] or "")

    out = executor.approve_and_execute(
        env["conn"], payload["call_id"], "m9-test",
        env["specs"], env["clients"])
    assert out["status"] == "executed"
    assert out["response"]["name"] == "HeldLead"
    assert approvals.list_pending(env["conn"], env["run_id"]) == []


def test_unmapped_deny_carries_call_id_receipt(env):
    gw = Gateway(MAP, env["conn"], env["run_id"], env["specs"],
                 env["clients"],
                 policy=_policy("default: allow\n"))
    resp = gw.handle_message(_call("nope_tool", {}))
    assert resp["error"]["code"] == -32000
    call_id = resp["error"]["data"]["call_id"]
    row = store.get_call(env["conn"], call_id)
    assert row["status"] == "blocked"
    assert row["system"] == "mcp"


def test_policy_sees_unmapped_tools_as_system_mcp(env):
    gw = Gateway(MAP, env["conn"], env["run_id"], env["specs"],
                 env["clients"],
                 policy=_policy(
                     "default: allow\nrules:\n"
                     "  - match: {system: mcp, operation: shady_tool}\n"
                     "    effect: require_approval\n"))
    resp = gw.handle_message(_call("shady_tool", {}))
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["result"] == approvals.PENDING
    row = store.get_call(env["conn"], payload["call_id"])
    assert row["operation"] == "shady_tool"


def test_decision_reason_is_stored_not_proven(env):
    conn, run_id = env["conn"], env["run_id"]
    out = executor.execute(
        conn, run_id, "crm", "nope.delete", {"id": "x"},
        specs=env["specs"], clients=env["clients"])
    assert out["status"] == "denied"
    # Pre-M9-style rows (NULL reason) verify fine...
    conn.execute("UPDATE calls SET decision_reason = NULL WHERE id = %s",
                 (out["call_id"],))
    assert store.verify_chain(conn, run_id)["ok"] is True
    # ...and mutating the reason never breaks the chain (by design).
    conn.execute("UPDATE calls SET decision_reason = 'forged' WHERE id = %s",
                 (out["call_id"],))
    assert store.verify_chain(conn, run_id)["ok"] is True
    assert store.get_call(conn, out["call_id"])["decision_reason"] == "forged"


def test_stamp_policy_export_and_redaction(env):
    conn, run_id = env["conn"], env["run_id"]
    store.stamp_policy(conn, run_id, "f" * 64)
    denied = executor.execute(
        conn, run_id, "crm", "leads.delete", {"lead_id": "x"},
        specs=env["specs"], clients=env["clients"],
        policy={"default": "deny", "rules": []})
    assert denied["status"] == "denied"
    held = executor.execute(
        conn, run_id, "crm", "nope.delete",
        {"client_secret": "shh", "nested": {"api_key": "shh-too"}},
        specs=env["specs"], clients=env["clients"], unknown="hold")
    approvals.decide(conn, held["call_id"], False, "m9-test")

    artifact = audit_export.export_run(conn, run_id)
    assert artifact["hyperion_audit"] == 1
    assert artifact["run"]["meta"]["policy_sha256"] == "f" * 64
    assert artifact["chain"]["ok"] is True
    by_op = {c["operation"]: c for c in artifact["calls"]}
    assert "policy denied" in by_op["leads.delete"]["decision_reason"]
    held_call = next(c for c in artifact["calls"]
                     if c["decision_reason"] == "unknown operation: held")
    assert held_call["args"] == {"client_secret": "[REDACTED]",
                                 "nested": {"api_key": "[REDACTED]"}}
    assert artifact["approvals"] == [
        {"call_id": held["call_id"], "status": "denied",
         "decided_by": "m9-test",
         "decided_at": artifact["approvals"][0]["decided_at"]}]
    assert artifact["approvals"][0]["decided_at"] is not None


def test_resume_policy_check(env):
    conn, run_id = env["conn"], env["run_id"]
    assert check_resume_policy(conn, run_id, "a" * 64) is None  # unstamped
    store.stamp_policy(conn, run_id, "a" * 64)
    assert check_resume_policy(conn, run_id, "a" * 64) is None
    mismatch = check_resume_policy(conn, run_id, "b" * 64)
    assert mismatch is not None and "refusing to mix policies" in mismatch


def test_cli_approvals_and_export(env, tmp_path, capsys):
    conn, run_id = env["conn"], env["run_id"]
    held = executor.execute(
        conn, run_id, "crm", "nope.delete", {"id": "x"},
        specs=env["specs"], clients=env["clients"], unknown="hold")

    assert cli_mod.main(["approvals", "--run", run_id]) == 0
    pending = json.loads(capsys.readouterr().out)
    assert [p["call_id"] for p in pending] == [held["call_id"]]

    out_file = tmp_path / "audit.json"
    assert cli_mod.main(["ledger", "export", "--run", run_id,
                         "--out", str(out_file)]) == 0
    artifact = json.loads(out_file.read_text(encoding="utf-8"))
    assert artifact["run"]["id"] == run_id
    assert artifact["chain"]["ok"] is True

    missing = str(uuid.uuid4())
    assert cli_mod.main(["ledger", "export", "--run", missing]) == 1
    assert cli_mod.main(["ledger", "export", "--run", "garbage"]) == 1
    assert cli_mod.main(["approvals", "--run", "garbage"]) == 1
    assert cli_mod.main(["ledger", "verify", "garbage"]) == 1


def test_gateway_refuses_to_start_on_bad_policy(tmp_path):
    bad_map = tmp_path / "tool_map.yaml"
    bad_map.write_text("policy: /nonexistent-hyperion-policy.yaml\n"
                       "tools: {}\n", encoding="utf-8")
    child_env = dict(os.environ)
    child_env["PYTHONPATH"] = os.pathsep.join(
        [str(REPO_ROOT / "src"), child_env.get("PYTHONPATH", "")])
    child_env["HYPERION_TOOL_MAP"] = str(bad_map)
    proc = subprocess.run(
        [sys.executable, "-m", "hyperion.mcp_gateway.proxy"],
        env=child_env, capture_output=True, text=True,
        cwd=str(REPO_ROOT), timeout=120)
    assert proc.returncode == 2
    assert "policy" in proc.stderr
