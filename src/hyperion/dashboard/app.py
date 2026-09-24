"""Dashboard read/execute API (M10): runs, live SSE, rollback, approvals.

Local demo tool, not a hardened service: CORS is scoped to localhost, and
write endpoints assume a trusted operator. Reads come straight from the
ledger; writes reuse the executor/rollback paths the CLI uses.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

import httpx  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from targets.crm import db as crm_db  # noqa: E402
from targets.crm.app import create_app as create_crm_app  # noqa: E402

from hyperion.config import load as load_config  # noqa: E402
from hyperion.executor import approvals, rollback_exec  # noqa: E402
from hyperion.executor import executor as ex  # noqa: E402
from hyperion.executor.clients import SystemClient  # noqa: E402
from hyperion.ledger import db, store  # noqa: E402
from hyperion.ledger import export as audit_export  # noqa: E402
from hyperion.systems.stripe_client import redact  # noqa: E402
from hyperion.systems.stripe_system import StripeSystemClient  # noqa: E402

POLL_SECONDS = 1.0


def load_dotenv_silent(path: Path) -> None:
    """Load KEY=VALUE lines into os.environ without ever printing values."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _ts(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _require_uuid(value: str, what: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise HTTPException(400, f"{value!r} is not a {what} id") from None


def _conn():
    conn = db.connect(load_config())
    db.migrate_up(conn)
    return conn


def _call_shape(row: dict) -> dict:
    return {
        "call_id": str(row["id"]),
        "seq": row["seq"],
        "system": row["system"],
        "operation": row["operation"],
        "args": redact(row["args"]),
        "effect_class": row["effect_class"],
        "status": row["status"],
        "decision_reason": row["decision_reason"],
        "spec_id": row["spec_id"],
        "spec_hash": row["spec_hash"],
        "entry_hash": row["entry_hash"],
        "started_at": _ts(row["started_at"]),
        "finished_at": _ts(row["finished_at"]),
    }


def _snapshot(conn, run_id: str) -> dict:
    calls = [_call_shape(r) for r in store.list_calls(conn, run_id)]
    return {
        "calls": calls,
        "edges": store.list_edges(conn, run_id),
        "approvals": [
            {**a, "decided_at": _ts(a["decided_at"])}
            for a in store.list_approvals(conn, run_id)
        ],
        "rollbacks": [
            {**rb, "started_at": _ts(rb["started_at"]),
             "finished_at": _ts(rb["finished_at"])}
            for rb in store.list_rollbacks(conn, run_id)
        ],
    }


def _fingerprint(snapshot: dict) -> str:
    slim = (
        [(c["call_id"], c["status"], c["finished_at"]) for c in snapshot["calls"]],
        [(a["call_id"], a["status"]) for a in snapshot["approvals"]],
        [(rb["id"], rb["status"],
          tuple((s["call_id"], s["status"], s["outcome"])
                for s in rb["steps"]))
         for rb in snapshot["rollbacks"]],
    )
    return json.dumps(slim, sort_keys=True, default=str)


class RollbackBody(BaseModel):
    # Empty targets means the whole run (the planner treats [] as no scope,
    # so the endpoint expands it explicitly).
    targets: list[str] = []
    mode: Literal["provenance", "linear"] = "provenance"
    force: bool = False


class DecideBody(BaseModel):
    by: str = ""


def boot_crm(port: int = 0) -> str:
    """Boot an embedded CRM (the app is stateless over shared Postgres,
    so any instance serves every run's objects). Port 0 asks the OS for
    a free port, so parallel/orphaned servers never collide."""
    crm_db.migrate_up()
    server = uvicorn.Server(
        uvicorn.Config(create_crm_app(), host="127.0.0.1", port=port,
                       log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 30
    while time.time() < deadline:
        bound_servers = getattr(server, "servers", None)
        if bound_servers and bound_servers[0].sockets:
            bound = bound_servers[0].sockets[0].getsockname()[1]
            url = f"http://127.0.0.1:{bound}"
            try:
                if httpx.get(f"{url}/snapshot", timeout=1).status_code == 200:
                    return url
            except Exception:
                pass
        elif not thread.is_alive():
            break
        time.sleep(0.2)
    raise RuntimeError("dashboard CRM server did not start")


def build_clients(crm_url: str) -> dict:
    clients: dict = {"crm": SystemClient(base_url=crm_url)}
    key = os.environ.get("STRIPE_TEST_KEY", "")
    if key:
        clients["stripe"] = StripeSystemClient(key)
    return clients


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_dotenv_silent(REPO_ROOT / ".env")
    conn = _conn()
    conn.close()
    crm_url = os.environ.get("CRM_BASE_URL") or boot_crm()
    app.state.clients = build_clients(crm_url)
    app.state.specs = ex.load_specs()
    yield
    for client in app.state.clients.values():
        close = getattr(client, "close", None)
        if close is not None:
            close()


app = FastAPI(title="Hyperion dashboard API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/runs")
def runs(limit: int = 20) -> dict:
    conn = _conn()
    try:
        return {"runs": [
            {**r, "started_at": _ts(r["started_at"])}
            for r in store.list_runs(conn, min(max(limit, 1), 100))
        ]}
    finally:
        conn.close()


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str) -> dict:
    run_id = _require_uuid(run_id, "run")
    conn = _conn()
    try:
        try:
            run = store.get_run(conn, run_id)
        except KeyError:
            raise HTTPException(404, f"run {run_id} not found") from None
        return {
            "run": {
                "id": str(run["id"]),
                "client": run["client"],
                "started_at": _ts(run["started_at"]),
                "meta": run["meta"],
            },
            **_snapshot(conn, run_id),
        }
    finally:
        conn.close()


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str, request: Request):
    run_id = _require_uuid(run_id, "run")

    def poll() -> dict | None:
        conn = _conn()
        try:
            try:
                store.get_run(conn, run_id)
            except KeyError:
                return None
            return _snapshot(conn, run_id)
        finally:
            conn.close()

    async def event_generator():
        last = ""
        idle = 0.0
        while True:
            if await request.is_disconnected():
                return
            try:
                snapshot = await asyncio.to_thread(poll)
            except Exception as e:
                # Transient DB failure: tell the client, keep the stream.
                yield ("data: " + json.dumps(
                    {"stream_error": f"{type(e).__name__}"}) + "\n\n")
                await asyncio.sleep(POLL_SECONDS)
                continue
            if snapshot is None:
                yield f"data: {json.dumps({'gone': True})}\n\n"
                return
            mark = _fingerprint(snapshot)
            if mark != last:
                last = mark
                idle = 0.0
                yield f"data: {json.dumps(snapshot, default=str)}\n\n"
            else:
                idle += POLL_SECONDS
                if idle >= 15.0:
                    idle = 0.0
                    yield ": keep-alive\n\n"
            await asyncio.sleep(POLL_SECONDS)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/runs/{run_id}/rollback")
def rollback(run_id: str, body: RollbackBody) -> dict:
    run_id = _require_uuid(run_id, "run")
    targets = [_require_uuid(t, "call") for t in body.targets]
    conn = _conn()
    try:
        try:
            store.get_run(conn, run_id)
        except KeyError:
            raise HTTPException(404, f"run {run_id} not found") from None
        if not targets:
            targets = [str(r["id"]) for r in store.list_calls(conn, run_id)]
        else:
            known = {str(r["id"]) for r in store.list_calls(conn, run_id)}
            stray = [t for t in targets if t not in known]
            if stray:
                raise HTTPException(
                    400, f"targets not in run {run_id}: {stray}") from None
        return rollback_exec.start(
            conn, run_id, targets, mode=body.mode, force=body.force,
            clients=app.state.clients, specs=app.state.specs)
    finally:
        conn.close()


@app.post("/api/approvals/{call_id}/approve")
def approve(call_id: str, body: DecideBody) -> dict:
    call_id = _require_uuid(call_id, "call")
    conn = _conn()
    try:
        try:
            store.get_call(conn, call_id)
        except KeyError:
            raise HTTPException(404, f"call {call_id} not found") from None
        out = ex.approve_and_execute(conn, call_id, body.by,
                                     app.state.specs, app.state.clients)
        if out["status"] not in ("executed", "already_executed"):
            raise HTTPException(409, out.get("reason", out["status"]))
        if isinstance(out.get("response"), dict):
            out["response"] = redact(out["response"])
        return out
    finally:
        conn.close()


@app.post("/api/approvals/{call_id}/deny")
def deny(call_id: str, body: DecideBody) -> dict:
    call_id = _require_uuid(call_id, "call")
    conn = _conn()
    try:
        try:
            store.get_call(conn, call_id)
        except KeyError:
            raise HTTPException(404, f"call {call_id} not found") from None
        out = approvals.decide(conn, call_id, False, body.by)
        if out["status"] == "error":
            raise HTTPException(404, out.get("reason", out["status"]))
        if out["status"] != "denied":
            raise HTTPException(409, f"already {out.get('decision', 'decided')}")
        return out
    finally:
        conn.close()


@app.get("/api/runs/{run_id}/export")
def export(run_id: str) -> dict:
    run_id = _require_uuid(run_id, "run")
    conn = _conn()
    try:
        try:
            return audit_export.export_run(conn, run_id)
        except KeyError:
            raise HTTPException(404, f"run {run_id} not found") from None
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Hyperion dashboard API")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
