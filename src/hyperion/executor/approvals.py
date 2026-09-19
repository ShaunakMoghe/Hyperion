"""Hold queue for irreversible (and held unknown) calls (H-021).

Held calls return a structured PENDING_APPROVAL result and never execute.
approve() runs the held call exactly once via a per-call idempotency key.
"""

from __future__ import annotations

import json
import uuid

import psycopg

from hyperion.ledger import store

PENDING = "PENDING_APPROVAL"


def hold_call(
    conn: psycopg.Connection,
    run_id: str,
    *,
    system: str,
    operation: str,
    args: dict,
    effect_class: str,
    fidelity_expected: str,
    spec_id: str | None,
    spec_hash: str | None,
    reason: str,
) -> dict:
    call = store.append_call(
        conn,
        run_id,
        system=system,
        operation=operation,
        args=args,
        effect_class=effect_class,
        fidelity_expected=fidelity_expected,
        status="held",
        spec_id=spec_id,
        spec_hash=spec_hash,
        idempotency_key=f"hold:{run_id}:{operation}:{_args_key(args)}",
    )
    existing = conn.execute(
        "SELECT id FROM approvals WHERE call_id = %s", (str(call["id"]),)
    ).fetchone()
    if existing is None:
        conn.execute(
            "INSERT INTO approvals (id, call_id, status) VALUES (%s, %s, 'pending')",
            (str(uuid.uuid4()), str(call["id"])),
        )
    return {
        "status": "held",
        "result": PENDING,
        "call_id": str(call["id"]),
        "reason": reason,
    }


def _args_key(args: dict) -> str:
    return json.dumps(args, sort_keys=True, separators=(",", ":"))


def decide(
    conn: psycopg.Connection, call_id: str, approve: bool, decided_by: str = ""
) -> dict:
    """Approve or deny a held call. Returns the decision outcome.

    Approving does NOT execute here; the executor's approve_and_execute()
    in executor.py performs the exactly-once execution. Calling decide()
    twice is safe: the second call reports already_decided.
    """
    rows = conn.execute(
        "SELECT status FROM approvals WHERE call_id = %s", (call_id,)
    ).fetchall()
    if not rows:
        return {"status": "error", "reason": f"no approval for call {call_id}"}
    if any(r[0] != "pending" for r in rows):
        decided = next(r[0] for r in rows if r[0] != "pending")
        return {"status": "already_decided", "decision": decided}
    decision = "approved" if approve else "denied"
    conn.execute(
        "UPDATE approvals SET status = %s, decided_by = %s, decided_at = now() "
        "WHERE call_id = %s AND status = 'pending'",
        (decision, decided_by, call_id),
    )
    if not approve:
        store.update_status(conn, call_id, "blocked")
    return {"status": decision, "call_id": call_id}
