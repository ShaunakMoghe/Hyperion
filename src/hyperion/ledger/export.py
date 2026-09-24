"""Portable audit export for a run (M9).

Collects what a reviewer needs — governing policy hash, hash-chain verdict,
every call with its decision reason, every approval with its decider — into
one JSON-serializable dict. Call args pass through the shared redact() so
secrets never leave in an export; responses and images are omitted, not
exported.
"""

from __future__ import annotations

from datetime import UTC, datetime

import psycopg
import psycopg.rows

from hyperion.ledger import store
from hyperion.systems.stripe_client import redact


def _ts(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def export_run(conn: psycopg.Connection, run_id: str) -> dict:
    """Build the audit artifact for a run. Raises KeyError when unknown."""
    run = store.get_run(conn, run_id)
    chain = store.verify_chain(conn, run_id)
    conn.row_factory = psycopg.rows.dict_row
    try:
        call_rows = conn.execute(
            """SELECT seq, system, operation, args, effect_class,
                      status, decision_reason, spec_id, spec_hash,
                      entry_hash, started_at, finished_at
               FROM calls WHERE run_id = %s ORDER BY seq""",
            (run_id,),
        ).fetchall()
        approval_rows = conn.execute(
            """SELECT a.call_id, a.status, a.decided_by, a.decided_at
               FROM approvals a JOIN calls c ON c.id = a.call_id
               WHERE c.run_id = %s ORDER BY c.seq""",
            (run_id,),
        ).fetchall()
    finally:
        conn.row_factory = psycopg.rows.tuple_row
    calls = [
        {
            "seq": r["seq"],
            "system": r["system"],
            "operation": r["operation"],
            "args": redact(r["args"]),
            "effect_class": r["effect_class"],
            "status": r["status"],
            "decision_reason": r["decision_reason"],
            "spec_id": r["spec_id"],
            "spec_hash": r["spec_hash"],
            "entry_hash": r["entry_hash"],
            "started_at": _ts(r["started_at"]),
            "finished_at": _ts(r["finished_at"]),
        }
        for r in (dict(r) for r in call_rows)
    ]
    approvals = [
        {
            "call_id": str(r["call_id"]),
            "status": r["status"],
            "decided_by": r["decided_by"],
            "decided_at": _ts(r["decided_at"]),
        }
        for r in (dict(r) for r in approval_rows)
    ]
    return {
        "hyperion_audit": 1,
        "exported_at": datetime.now(UTC).isoformat(),
        "run": {
            "id": str(run["id"]),
            "client": run["client"],
            "started_at": _ts(run["started_at"]),
            "meta": run["meta"],
        },
        "chain": chain,
        "calls": calls,
        "approvals": approvals,
    }
