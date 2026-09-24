"""M10: dashboard API against real Postgres + live CRM (no mocks)."""

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from hyperion.dashboard.app import app
from hyperion.executor import executor
from hyperion.ledger import store

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def live_base():
    """Real HTTP server for the SSE test (TestClient can't bound an
    infinite stream; httpx timeouts can)."""
    import threading
    import time

    import httpx
    import uvicorn

    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 30
    while time.time() < deadline:
        bound_servers = getattr(server, "servers", None)
        if bound_servers and bound_servers[0].sockets:
            url = ("http://127.0.0.1:"
                   f"{bound_servers[0].sockets[0].getsockname()[1]}")
            try:
                if httpx.get(f"{url}/api/health",
                             timeout=1).status_code == 200:
                    yield url
                    break
            except Exception:
                pass
        time.sleep(0.2)
    else:
        raise RuntimeError("dashboard test server did not start")
    server.should_exit = True
    thread.join(timeout=15)


def _lead_run(env):
    conn, run_id = env["conn"], env["run_id"]
    out = executor.execute(conn, run_id, "crm", "leads.create",
                           {"name": "DashLead"}, specs=env["specs"],
                           clients=env["clients"])
    assert out["status"] == "executed"
    return run_id, out


def test_health(client):
    assert client.get("/api/health").json() == {"ok": True}


def test_runs_lists_newest_first(client, env):
    first = store.create_run(env["conn"], client="dash-first")
    second = store.create_run(env["conn"], client="dash-second")
    body = client.get("/api/runs?limit=50").json()
    ids = [r["id"] for r in body["runs"]]
    assert ids.index(second) < ids.index(first)
    row = next(r for r in body["runs"] if r["id"] == second)
    assert row["client"] == "dash-second"
    assert row["calls"] == 0
    assert row["by_status"] == {}


def test_run_detail_shape(client, env):
    run_id, out = _lead_run(env)
    body = client.get(f"/api/runs/{run_id}").json()
    assert body["run"]["id"] == run_id
    assert [c["call_id"] for c in body["calls"]] == [out["call_id"]]
    call = body["calls"][0]
    assert call["operation"] == "leads.create"
    assert call["status"] == "executed"
    assert "response" not in call  # responses/images never exported
    assert body["edges"] == []
    assert body["approvals"] == []


def test_run_events_streams_snapshot(live_base, env):
    import httpx

    run_id, _ = _lead_run(env)
    with httpx.Client(base_url=live_base, timeout=10) as http:
        with http.stream("GET", f"/api/runs/{run_id}/events") as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith(
                "text/event-stream")
            for line in resp.iter_lines():
                if line.startswith("data:"):
                    snapshot = json.loads(line[5:])
                    assert [c["operation"] for c in snapshot["calls"]] == [
                        "leads.create"]
                    return
    raise AssertionError("no SSE data received")


def test_rollback_executes(client, env):
    run_id, out = _lead_run(env)
    body = client.post(f"/api/runs/{run_id}/rollback", json={}).json()
    assert body["status"] == "completed", body
    code, _ = env["clients"]["crm"].request(
        "GET", "/leads/{lead_id}", {"lead_id": out["produced"]["lead_id"]})
    assert code == 410


def test_approve_and_deny_flow(client, env):
    conn, run_id = env["conn"], env["run_id"]
    held = executor.execute(
        conn, run_id, "crm", "leads.create", {"name": "DashHeld"},
        specs=env["specs"], clients=env["clients"],
        policy={"default": "allow", "rules": [
            {"match": {"system": "crm", "operation": "leads.create"},
             "effect": "require_approval"}]})
    assert held["status"] == "held"
    approved = client.post(
        f"/api/approvals/{held['call_id']}/approve",
        json={"by": "dash-test"}).json()
    assert approved["status"] == "executed"
    assert approved["response"]["name"] == "DashHeld"

    held2 = executor.execute(
        conn, run_id, "crm", "nope.delete", {"id": "x"},
        specs=env["specs"], clients=env["clients"], unknown="hold")
    denied = client.post(
        f"/api/approvals/{held2['call_id']}/deny",
        json={"by": "dash-test"}).json()
    assert denied["status"] == "denied"


def test_export_matches_audit_artifact(client, env):
    run_id, _ = _lead_run(env)
    body = client.get(f"/api/runs/{run_id}/export").json()
    assert body["hyperion_audit"] == 1
    assert body["run"]["id"] == run_id
    assert body["chain"]["ok"] is True


def test_bad_ids_rejected(client):
    assert client.get("/api/runs/garbage").status_code == 400
    assert client.get(f"/api/runs/{uuid.uuid4()}").status_code == 404
    assert client.post("/api/approvals/garbage/approve",
                       json={}).status_code == 400
    assert client.post(f"/api/approvals/{uuid.uuid4()}/deny",
                       json={}).status_code == 404
    assert client.get(f"/api/runs/{uuid.uuid4()}/export").status_code == 404
    assert client.post(f"/api/runs/{uuid.uuid4()}/rollback",
                       json={}).status_code == 404
    assert client.post(f"/api/approvals/{uuid.uuid4()}/approve",
                       json={}).status_code == 404


def test_rollback_rejects_stray_targets_and_modes(client, env):
    run_id, out = _lead_run(env)
    other_run = store.create_run(env["conn"], client="dash-other")
    other = executor.execute(
        env["conn"], other_run, "crm", "leads.create", {"name": "Other"},
        specs=env["specs"], clients=env["clients"])
    # Unknown target, cross-run target, and bad mode all fail cleanly.
    resp = client.post(f"/api/runs/{run_id}/rollback",
                       json={"targets": [str(uuid.uuid4())]})
    assert resp.status_code == 400
    resp = client.post(f"/api/runs/{run_id}/rollback",
                       json={"targets": [other["call_id"]]})
    assert resp.status_code == 400
    resp = client.post(f"/api/runs/{run_id}/rollback",
                       json={"mode": "sideways"})
    assert resp.status_code == 422
    # Targeted rollback of the one call still works.
    resp = client.post(f"/api/runs/{run_id}/rollback",
                       json={"targets": [out["call_id"]]})
    assert resp.json()["status"] == "completed"


def test_double_decide_conflicts(client, env):
    conn, run_id = env["conn"], env["run_id"]
    held = executor.execute(
        conn, run_id, "crm", "nope.delete", {"id": "x"},
        specs=env["specs"], clients=env["clients"], unknown="hold")
    assert client.post(f"/api/approvals/{held['call_id']}/deny",
                       json={}).status_code == 200
    assert client.post(f"/api/approvals/{held['call_id']}/deny",
                       json={}).status_code == 409
    assert client.post(f"/api/approvals/{held['call_id']}/approve",
                       json={}).status_code == 409
    # Executed calls have no approval row to deny.
    _, executed = _lead_run(env)
    assert client.post(f"/api/approvals/{executed['call_id']}/deny",
                       json={}).status_code == 404
    assert client.post(f"/api/approvals/{executed['call_id']}/approve",
                       json={}).status_code == 409


def test_sse_unknown_run_says_gone(live_base, env):
    import httpx

    missing = str(uuid.uuid4())
    with httpx.Client(base_url=live_base, timeout=10) as http:
        with http.stream("GET", f"/api/runs/{missing}/events") as resp:
            assert resp.status_code == 200
            for line in resp.iter_lines():
                if line.startswith("data:"):
                    assert json.loads(line[5:]) == {"gone": True}
                    return
    raise AssertionError("no SSE data received")


def test_sse_bad_uuid_rejected(live_base):
    import httpx

    with httpx.Client(base_url=live_base, timeout=10) as http:
        resp = http.get("/api/runs/garbage/events")
        assert resp.status_code == 400
