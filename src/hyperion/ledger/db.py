"""Postgres helpers + versioned migration runner (H-010).

Uses pathlib throughout; connection string comes from Config (env).
"""

from __future__ import annotations

import re
from pathlib import Path

import psycopg

from hyperion.config import Config, load

_MIG_RE = re.compile(r"^(\d+)_.+\.up\.sql$")


def migrations_dir() -> Path:
    return Path(__file__).resolve().parent / "migrations"


def connect(cfg: Config | None = None) -> psycopg.Connection:
    cfg = cfg or load()
    return psycopg.connect(cfg.database_url, autocommit=True)


def _discover(mig_dir: Path | None = None) -> list[tuple[int, Path, Path]]:
    """Return (version, up_path, down_path) triples sorted by version."""
    mig_dir = mig_dir or migrations_dir()
    found: list[tuple[int, Path, Path]] = []
    for up in sorted(mig_dir.glob("*.up.sql")):
        m = _MIG_RE.match(up.name)
        if not m:
            continue
        version = int(m.group(1))
        down = up.with_name(up.name[: -len(".up.sql")] + ".down.sql")
        if not down.is_file():
            raise FileNotFoundError(f"migration {up.name} has no down file {down.name}")
        found.append((version, up, down))
    return found


def applied_versions(
    conn: psycopg.Connection, table: str = "schema_migrations"
) -> list[int]:
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {table} "
        "(version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
    )
    rows = conn.execute(f"SELECT version FROM {table} ORDER BY version").fetchall()
    return [r[0] for r in rows]


def migrate_up(
    conn: psycopg.Connection,
    mig_dir: Path | None = None,
    table: str = "schema_migrations",
) -> list[int]:
    """Apply pending migrations in order; return newly applied versions."""
    applied = set(applied_versions(conn, table))
    new: list[int] = []
    for version, up, _down in _discover(mig_dir):
        if version in applied:
            continue
        conn.execute(up.read_text(encoding="utf-8"))
        conn.execute(f"INSERT INTO {table} (version) VALUES (%s)", (version,))
        new.append(version)
    return new


def migrate_down(
    conn: psycopg.Connection,
    to_version: int = 0,
    mig_dir: Path | None = None,
    table: str = "schema_migrations",
) -> list[int]:
    """Roll back applied migrations down to (and excluding) to_version."""
    applied = [v for v in applied_versions(conn, table) if v > to_version]
    by_version = {v: (up, down) for v, up, down in _discover(mig_dir)}
    rolled: list[int] = []
    for version in sorted(applied, reverse=True):
        if version not in by_version:
            raise RuntimeError(f"applied migration {version} has no files on disk")
        _up, down = by_version[version]
        conn.execute(down.read_text(encoding="utf-8"))
        # The tracking table itself may have been dropped by the down script.
        try:
            conn.execute(f"DELETE FROM {table} WHERE version = %s", (version,))
        except psycopg.errors.UndefinedTable:
            pass
        rolled.append(version)
    return rolled
