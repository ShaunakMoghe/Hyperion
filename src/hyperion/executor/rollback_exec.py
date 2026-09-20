"""Rollback executor (H-023): persisted, idempotent, resumable state machine.

Each step runs: drift check (current vs recorded post-image) -> inverse ->
verify by re-reading. Outcomes are persisted per step; killing the process
mid-rollback and calling resume() completes without double-applying any
inverse (already-undone inverses verify instead of failing).
"""

from __future__ import annotations

import json
import uuid

import psycopg
import psycopg.rows

from hyperion.executor import executor as ex
from hyperion.executor import rollback_plan as planner
from hyperion.executor.clients import fill_path
from hyperion.ledger import store

TERMINAL_STEP = {"done", "error"}


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def start(
    conn: psycopg.Connection,
    run_id: str,
    targets: list[str],
    *,
    mode: str = "provenance",
    force: bool = False,
    clients: dict | None = None,
    specs: dict[str, dict] | None = None,
    step_hook=None,
) -> dict:
    """Plan, persist, and run a rollback. Refuses blocked plans w/o force."""
    rollback_id = persist(conn, run_id, targets, mode=mode, force=force)
    if rollback_id is None:
        return {"status": "blocked",
                "plan": planner.plan(conn, run_id, targets, mode=mode,
                                     force=force)}
    return _drive(conn, rollback_id, clients or {}, specs or ex.load_specs(),
                  step_hook)


def persist(
    conn: psycopg.Connection,
    run_id: str,
    targets: list[str],
    *,
    mode: str = "provenance",
    force: bool = False,
) -> str | None:
    """Plan and persist a rollback without running it. Returns the
    rollback id, or None when the plan is blocked (use force)."""
    the_plan = planner.plan(conn, run_id, targets, mode=mode, force=force)
    if the_plan["status"] == "blocked":
        return None
    rollback_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO rollbacks (id, run_id, target_call_ids, plan, status)
           VALUES (%s, %s, %s, %s, 'running')""",
        (rollback_id, run_id, json.dumps(targets), json.dumps(the_plan)),
    )
    for step in the_plan["steps"]:
        conn.execute(
            """INSERT INTO rollback_steps
               (id, rollback_id, call_id, status, idempotency_key)
               VALUES (%s, %s, %s, 'pending', %s)""",
            (str(uuid.uuid4()), rollback_id, step["call_id"],
             f"rb:{rollback_id}:{step['call_id']}"),
        )
    return rollback_id


def resume(
    conn: psycopg.Connection,
    rollback_id: str,
    clients: dict,
    specs: dict[str, dict],
    step_hook=None,
) -> dict:
    """Resume an interrupted rollback; finished steps never re-run."""
    return _drive(conn, rollback_id, clients, specs, step_hook)


def _drive(conn, rollback_id, clients, specs, step_hook) -> dict:
    steps = _pending_steps(conn, rollback_id)
    outcomes: dict[str, str] = {}
    for step_id, call_id in steps:
        outcome = _run_step(conn, step_id, call_id, clients, specs, step_hook)
        outcomes[call_id] = outcome
    failed = _count_failed(conn, rollback_id)
    status = "failed" if failed else "completed"
    conn.execute(
        "UPDATE rollbacks SET status = %s, finished_at = now() WHERE id = %s",
        (status, rollback_id),
    )
    return {"status": status, "rollback_id": rollback_id, "outcomes": outcomes}


def _pending_steps(conn, rollback_id) -> list[tuple[str, str]]:
    conn.row_factory = psycopg.rows.dict_row
    try:
        rows = conn.execute(
            """SELECT s.id AS sid, s.call_id AS cid, c.seq AS seq
               FROM rollback_steps s JOIN calls c ON c.id = s.call_id
               WHERE s.rollback_id = %s AND s.status NOT IN ('done', 'error')
               ORDER BY c.seq DESC""",
            (rollback_id,),
        ).fetchall()
    finally:
        conn.row_factory = psycopg.rows.tuple_row
    return [(str(r["sid"]), str(r["cid"])) for r in rows]


def _count_failed(conn, rollback_id) -> int:
    row = conn.execute(
        """SELECT COUNT(*) FROM rollback_steps WHERE rollback_id = %s
           AND (status = 'error' OR outcome = 'verify_failed')""",
        (rollback_id,),
    ).fetchone()
    return int(row[0])


def _finish_step(conn, step_id, status, outcome, fidelity=None, evidence=None):
    conn.execute(
        """UPDATE rollback_steps SET status = %s, outcome = %s,
           fidelity_achieved = %s, evidence = %s WHERE id = %s""",
        (status, outcome, fidelity, json.dumps(evidence or {}), step_id),
    )


def _produced_from_response(spec: dict, response: dict | None) -> dict:
    produced: dict = {}
    for p in spec.get("produces", []):
        produced[p["name"]] = ex.lookup({"response": response}, p["from"][2:])
    return produced


def _run_step(conn, step_id, call_id, clients, specs, step_hook) -> str:
    conn.execute("UPDATE rollback_steps SET status = 'running' WHERE id = %s",
                 (step_id,))
    call = store.get_call(conn, call_id)
    spec = specs.get(f"{call['system']}.{call['operation']}")
    if spec is None or call["status"] != "executed":
        _finish_step(conn, step_id, "error", "error",
                     evidence={"reason": "no spec or not executed"})
        return "error"
    if spec["effect_class"] == "irreversible":
        # Only reachable with force; nothing can undo it.
        _finish_step(conn, step_id, "done", "skipped_irreversible",
                     fidelity="none")
        store.update_status(conn, call_id, "conflict")
        return "skipped_irreversible"
    client = clients.get(call["system"])
    if client is None:
        _finish_step(conn, step_id, "error", "error",
                     evidence={"reason": f"no client for {call['system']}"})
        return "error"
    try:
        produced = _produced_from_response(spec, call["response"])
    except KeyError as e:
        _finish_step(conn, step_id, "error", "error",
                     evidence={"reason": f"produced id unrecoverable: {e}"})
        return "error"

    args = call["args"] or {}
    before = call["before_image"]

    # 1. Drift check: current state must match the recorded post-image.
    if call["post_image"] is not None:
        try:
            current_post = _read_post(client, spec, args, produced)
        except Exception as e:
            _finish_step(conn, step_id, "error", "error",
                         evidence={"reason": f"drift read: {type(e).__name__}"})
            return "error"
        if current_post is None or _canonical(current_post) != _canonical(
            call["post_image"]
        ):
            _finish_step(conn, step_id, "done", "conflict_detected",
                         evidence={"reason": "post-image drift"})
            store.update_status(conn, call_id, "conflict")
            return "conflict_detected"

    # 2. Inverse.
    if step_hook is not None:
        step_hook({"step_id": step_id, "call_id": call_id}, call, spec)
    inv = spec["inverse"]
    try:
        params = ex.resolve_params(inv.get("params", {}), args, produced or None)
        body = {}
        for field in inv.get("body_from_before_image", []):
            if not isinstance(before, dict) or field not in before:
                raise KeyError(f"before-image lacks {field!r}")
            body[field] = before[field]
        method, path = inv["operation"]["method"], inv["operation"]["path"]
        filled, _ = fill_path(path, params)
        if method.upper() in ("POST", "PUT", "PATCH"):
            code, _ = client.request(method, filled, body)
        else:
            code, _ = client.request(method, filled, {})
    except KeyError as e:
        _finish_step(conn, step_id, "error", "error",
                     evidence={"reason": f"inverse unresolvable: {e}"})
        return "error"
    except Exception as e:
        _finish_step(conn, step_id, "error", "error",
                     evidence={"reason": f"inverse transport: {type(e).__name__}"})
        return "error"

    inverse_ok = code is not None and 200 <= code < 300
    replay = False
    if not inverse_ok and code in (404, 410):
        # Possibly already undone (e.g. resume after a crash): verify decides.
        replay = True
    elif not inverse_ok:
        _finish_step(conn, step_id, "error", "error",
                     evidence={"reason": f"inverse returned {code}"})
        return "error"

    # 3. Verify by re-reading.
    try:
        outcome, fidelity = _verify(client, spec, args, produced, before)
    except Exception as e:
        _finish_step(conn, step_id, "error", "error",
                     evidence={"reason": f"verify read: {type(e).__name__}"})
        return "error"
    if outcome in ("restored_exact", "restored_equivalent", "compensated"):
        _finish_step(conn, step_id, "done", outcome, fidelity,
                     evidence={"replay": replay} if replay else None)
        store.update_status(conn, call_id, "rolled_back")
    else:
        _finish_step(conn, step_id, "error", "verify_failed",
                     evidence={"replay": replay})
    return outcome


def _read_post(client, spec, args, produced):
    verify = spec.get("verify")
    if verify and produced:
        code, post = ex._read_state(client, verify["read"], args, produced)
        return post if isinstance(post, dict) else None
    if spec.get("before_image"):
        code, post = ex._read_state(client, spec["before_image"]["read"], args)
        if isinstance(post, dict):
            return {f: post.get(f) for f in spec["before_image"]["fields"]}
    return None


def _verify(client, spec, args, produced, before) -> tuple[str, str | None]:
    """Re-read state and compare per declared fidelity."""
    fidelity = spec["fidelity"]
    verify = spec["verify"]
    try:
        code, body = ex._read_state(client, verify["read"], args,
                                    produced or None)
    except KeyError:
        return "verify_failed", None

    if spec["effect_class"] == "compensable":
        # Net effect offset is proven by the accepted inverse call itself.
        return "compensated", "compensated"

    if before is None:
        # Create-style: success means the object is gone (exact) or
        # tombstoned (equivalent).
        if code == 404:
            return "restored_exact", "exact"
        if code == 410 and fidelity == "equivalent":
            return "restored_equivalent", "equivalent"
        return "verify_failed", None

    if code == 404 or code == 410:
        if fidelity == "equivalent":
            return "restored_equivalent", "equivalent"
        return "verify_failed", None
    if not isinstance(body, dict):
        return "verify_failed", None
    fields = verify["compare"]["fields"]
    if all(body.get(f) == before.get(f) for f in fields):
        if fidelity == "exact":
            return "restored_exact", "exact"
        return "restored_equivalent", "equivalent"
    return "verify_failed", None
