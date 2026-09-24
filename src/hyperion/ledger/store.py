"""Effect-ledger API + hash chain (H-012).

entry_hash = sha256(prev_hash || canonical_json(entry_without_hash)),
chained per run. `verify_chain` recomputes and reports the first broken link.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

import psycopg
import psycopg.rows

GENESIS = "GENESIS"


def _canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _hash(prev_hash: str, payload: dict) -> str:
    return hashlib.sha256((prev_hash + _canonical(payload)).encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def create_run(
    conn: psycopg.Connection, client: str = "", meta: dict | None = None
) -> str:
    run_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO runs (id, client, meta) VALUES (%s, %s, %s)",
        (run_id, client, json.dumps(meta or {})),
    )
    return run_id


def get_run(conn: psycopg.Connection, run_id: str) -> dict:
    conn.row_factory = psycopg.rows.dict_row
    try:
        row = conn.execute("SELECT * FROM runs WHERE id = %s", (run_id,)).fetchone()
    finally:
        conn.row_factory = psycopg.rows.tuple_row
    if row is None:
        raise KeyError(f"run {run_id} not found")
    return dict(row)


def stamp_policy(conn: psycopg.Connection, run_id: str, policy_sha256: str) -> None:
    """Record the governing policy's sha256 in the run's meta (M9).

    Called once at run creation by policy-enforcing entry points; the run's
    governing policy is fixed at creation so an audit export can say what
    rules were in force.
    """
    conn.execute(
        "UPDATE runs SET meta = meta || %s::jsonb WHERE id = %s",
        (json.dumps({"policy_sha256": policy_sha256}), run_id),
    )


def _last_hash(conn: psycopg.Connection, run_id: str) -> str:
    row = conn.execute(
        "SELECT entry_hash FROM calls WHERE run_id = %s ORDER BY seq DESC LIMIT 1",
        (run_id,),
    ).fetchone()
    return row[0] if row else GENESIS


def _next_seq(conn: psycopg.Connection, run_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(seq), -1) + 1 FROM calls WHERE run_id = %s", (run_id,)
    ).fetchone()
    return int(row[0])


def append_call(
    conn: psycopg.Connection,
    run_id: str,
    *,
    system: str,
    operation: str,
    args: dict | None = None,
    effect_class: str,
    fidelity_expected: str,
    status: str = "executed",
    before_image: dict | None = None,
    response: dict | None = None,
    post_image: dict | None = None,
    spec_id: str | None = None,
    spec_hash: str | None = None,
    idempotency_key: str | None = None,
    decision_reason: str | None = None,
) -> dict:
    """Append a call; returns the row. Existing idempotency_key returns the
    original row without writing a duplicate (exactly-once support)."""
    if idempotency_key:
        row = conn.execute(
            "SELECT id FROM calls WHERE idempotency_key = %s", (idempotency_key,)
        ).fetchone()
        if row:
            return get_call(conn, str(row[0]))
    call_id = str(uuid.uuid4())
    seq = _next_seq(conn, run_id)
    prev_hash = _last_hash(conn, run_id)
    started = _now()
    payload = {
        "id": call_id,
        "run_id": run_id,
        "seq": seq,
        "system": system,
        "operation": operation,
        "args": args or {},
        "effect_class": effect_class,
        "fidelity_expected": fidelity_expected,
        "before_image": before_image,
        "response": response,
        "post_image": post_image,
        "spec_id": spec_id,
        "spec_hash": spec_hash,
        "idempotency_key": idempotency_key,
        "started_at": started.isoformat(),
    }
    entry_hash = _hash(prev_hash, payload)
    conn.execute(
        """INSERT INTO calls (id, run_id, seq, system, operation, args,
                              effect_class, fidelity_expected, status,
                              before_image, response, post_image, spec_id,
                              spec_hash, idempotency_key, started_at,
                              prev_hash, entry_hash, decision_reason)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                   %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            call_id,
            run_id,
            seq,
            system,
            operation,
            json.dumps(args or {}),
            effect_class,
            fidelity_expected,
            status,
            json.dumps(before_image) if before_image is not None else None,
            json.dumps(response) if response is not None else None,
            json.dumps(post_image) if post_image is not None else None,
            spec_id,
            spec_hash,
            idempotency_key,
            started,
            prev_hash,
            entry_hash,
            decision_reason,
        ),
    )
    return get_call(conn, call_id)


def update_status(
    conn: psycopg.Connection, call_id: str, status: str, finished: bool = True
) -> None:
    """Update a call's status. Status/finished_at are mutable executor state
    and are excluded from the hash chain on purpose; the chain covers the
    append-time record (args, images, response, spec linkage)."""
    if finished:
        conn.execute(
            "UPDATE calls SET status = %s, finished_at = now() WHERE id = %s",
            (status, call_id),
        )
    else:
        conn.execute("UPDATE calls SET status = %s WHERE id = %s", (status, call_id))


def add_edge(
    conn: psycopg.Connection,
    call_id: str,
    depends_on_call_id: str,
    kind: str,
    evidence: dict | None = None,
) -> None:
    conn.execute(
        """INSERT INTO edges (call_id, depends_on_call_id, kind, evidence)
           VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING""",
        (call_id, depends_on_call_id, kind, json.dumps(evidence or {})),
    )


def get_call(conn: psycopg.Connection, call_id: str) -> dict:
    conn.row_factory = psycopg.rows.dict_row
    try:
        row = conn.execute("SELECT * FROM calls WHERE id = %s", (call_id,)).fetchone()
    finally:
        conn.row_factory = psycopg.rows.tuple_row
    if row is None:
        raise KeyError(f"call {call_id} not found")
    return dict(row)


def _payload_of(row: dict) -> dict:
    # decision_reason is executor state like status: stored, never hashed.
    return {
        "id": str(row["id"]),
        "run_id": str(row["run_id"]),
        "seq": row["seq"],
        "system": row["system"],
        "operation": row["operation"],
        "args": row["args"],
        "effect_class": row["effect_class"],
        "fidelity_expected": row["fidelity_expected"],
        "before_image": row["before_image"],
        "response": row["response"],
        "post_image": row["post_image"],
        "spec_id": row["spec_id"],
        "spec_hash": row["spec_hash"],
        "idempotency_key": row["idempotency_key"],
        "started_at": row["started_at"].isoformat()
        if isinstance(row["started_at"], datetime)
        else str(row["started_at"]),
    }


def verify_chain(conn: psycopg.Connection, run_id: str) -> dict:
    """Recompute the chain; report the first broken entry, if any.

    Mutable executor state (status, finished_at, decision_reason) is
    excluded from the hash by design; tampering with those fields is NOT
    detected (limitation)."""
    conn.row_factory = psycopg.rows.dict_row
    try:
        rows = conn.execute(
            "SELECT * FROM calls WHERE run_id = %s ORDER BY seq", (run_id,)
        ).fetchall()
    finally:
        conn.row_factory = psycopg.rows.tuple_row
    prev = GENESIS
    for row in rows:
        row = dict(row)
        if row["prev_hash"] != prev:
            return {"ok": False, "first_broken_call_id": str(row["id"]),
                    "reason": "prev_hash link broken"}
        if _hash(prev, _payload_of(row)) != row["entry_hash"]:
            return {"ok": False, "first_broken_call_id": str(row["id"]),
                    "reason": "entry hash mismatch"}
        prev = row["entry_hash"]
    return {"ok": True, "calls": len(rows)}
