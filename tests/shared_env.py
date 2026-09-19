"""Shared fixtures: real Postgres + real CRM over real HTTP (no mocks)."""

import threading
import time

import httpx
import pytest
import uvicorn
from targets.crm import db as crm_db
from targets.crm.app import create_app

from hyperion.config import load
from hyperion.executor import executor
from hyperion.executor.clients import SystemClient
from hyperion.ledger import db, store

CRM_PORT = 18001


@pytest.fixture(scope="session")
def crm_base_url():
    """Boot the real CRM app on localhost; session-scoped for speed."""
    conn = db.connect(load())
    db.migrate_up(conn)
    conn.close()
    crm_db.migrate_up()
    server = uvicorn.Server(
        uvicorn.Config(create_app(), host="127.0.0.1", port=CRM_PORT,
                       log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 30
    url = f"http://127.0.0.1:{CRM_PORT}"
    while time.time() < deadline:
        try:
            if httpx.get(f"{url}/snapshot", timeout=1).status_code == 200:
                break
        except Exception:
            time.sleep(0.2)
    else:
        raise RuntimeError("crm test server did not start")
    yield url
    server.should_exit = True
    thread.join(timeout=15)


@pytest.fixture()
def env(crm_base_url):
    """Per-test executor environment: fresh run, specs, live CRM client."""
    conn = db.connect(load())
    run_id = store.create_run(conn, client="test")
    clients = {"crm": SystemClient(base_url=crm_base_url)}
    specs = executor.load_specs()
    yield {"conn": conn, "run_id": run_id, "clients": clients, "specs": specs}
    clients["crm"].close()
    conn.close()
