"""Mini-CRM database helpers (H-013)."""

from __future__ import annotations

from pathlib import Path

import psycopg

from hyperion.config import Config, load
from hyperion.ledger import db as migrations

# Unqualified on purpose: the runner creates the tracking table before any
# migration runs, so it cannot live inside the `crm` schema itself.
TRACKING_TABLE = "crm_schema_migrations"


def migrations_dir() -> Path:
    return Path(__file__).resolve().parent / "migrations"


def connect(cfg: Config | None = None) -> psycopg.Connection:
    cfg = cfg or load()
    return psycopg.connect(cfg.database_url, autocommit=True)


def migrate_up(conn: psycopg.Connection | None = None) -> list[int]:
    own = conn is None
    conn = conn or connect()
    try:
        return migrations.migrate_up(
            conn, mig_dir=migrations_dir(), table=TRACKING_TABLE
        )
    finally:
        if own:
            conn.close()
