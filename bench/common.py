"""Shared bench helpers: silent .env loading and CRM boot."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

import httpx  # noqa: E402
import uvicorn  # noqa: E402
from targets.crm import db as crm_db  # noqa: E402
from targets.crm.app import create_app  # noqa: E402

from hyperion.config import load as load_config  # noqa: E402
from hyperion.ledger import db  # noqa: E402

CRM_PORT = 18002


def load_dotenv_silent(path: Path) -> None:
    """Load KEY=VALUE lines into os.environ without ever printing values."""
    import os

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def boot_crm() -> tuple[str, uvicorn.Server, threading.Thread]:
    """Boot the real CRM app on localhost (mirrors tests/shared_env)."""
    load_dotenv_silent(REPO_ROOT / ".env")
    conn = db.connect(load_config())
    db.migrate_up(conn)
    conn.close()
    crm_db.migrate_up()
    server = uvicorn.Server(
        uvicorn.Config(create_app(), host="127.0.0.1", port=CRM_PORT,
                       log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{CRM_PORT}"
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            if httpx.get(f"{url}/snapshot", timeout=1).status_code == 200:
                return url, server, thread
        except Exception:
            time.sleep(0.2)
    raise RuntimeError("bench CRM server did not start")
