"""Rollback planner (H-022, dry run).

Rolling back X undoes X plus every call depending on X (transitive closure),
dependents first. Independent calls are untouched. Modes: provenance
(declared + provenance edges) and linear (v1-style: each call depends on its
predecessor in the run).
"""

from __future__ import annotations

import psycopg
import psycopg.rows

EXPECTED = {
    ("reversible", "exact"): "restored_exact",
    ("reversible", "equivalent"): "restored_equivalent",
    ("compensable", "compensated"): "compensated",
    ("read", "exact"): "skipped_read",
}


def _calls(conn: psycopg.Connection, run_id: str) -> dict[str, dict]:
    conn.row_factory = psycopg.rows.dict_row
    try:
        rows = conn.execute(
            "SELECT * FROM calls WHERE run_id = %s ORDER BY seq", (run_id,)
        ).fetchall()
    finally:
        conn.row_factory = psycopg.rows.tuple_row
    return {str(r["id"]): dict(r) for r in rows}


def _edges(
    conn: psycopg.Connection, call_ids: set[str], mode: str
) -> dict[str, set[str]]:
    """Map each call to the set it directly depends on."""
    deps: dict[str, set[str]] = {c: set() for c in call_ids}
    if mode == "linear":
        conn.row_factory = psycopg.rows.dict_row
        try:
            rows = conn.execute(
                "SELECT id, seq FROM calls WHERE id = ANY(%s) ORDER BY seq",
                (list(call_ids),),
            ).fetchall()
        finally:
            conn.row_factory = psycopg.rows.tuple_row
        prev = None
        for r in rows:
            cid = str(r["id"])
            if prev is not None:
                deps[cid].add(prev)
            prev = cid
        return deps
    if mode != "provenance":
        raise ValueError(f"unknown planner mode {mode!r}")
    conn.row_factory = psycopg.rows.dict_row
    try:
        rows = conn.execute(
            """SELECT call_id, depends_on_call_id FROM edges
               WHERE call_id = ANY(%s) AND kind IN ('provenance', 'declared')""",
            (list(call_ids),),
        ).fetchall()
    finally:
        conn.row_factory = psycopg.rows.tuple_row
    for r in rows:
        if str(r["depends_on_call_id"]) in deps:
            deps[str(r["call_id"])].add(str(r["depends_on_call_id"]))
    return deps


def _closure(deps: dict[str, set[str]], targets: list[str]) -> set[str]:
    """Targets plus everything transitively depending on them."""
    reverse: dict[str, set[str]] = {c: set() for c in deps}
    for c, ds in deps.items():
        for d in ds:
            reverse[d].add(c)
    seen = set(targets)
    stack = list(targets)
    while stack:
        cur = stack.pop()
        for dependent in reverse.get(cur, set()):
            if dependent not in seen:
                seen.add(dependent)
                stack.append(dependent)
    return seen


def plan(
    conn: psycopg.Connection,
    run_id: str,
    targets: list[str],
    *,
    mode: str = "provenance",
    force: bool = False,
) -> dict:
    """Dry-run plan. Never executes anything."""
    calls = _calls(conn, run_id)
    unknown = [t for t in targets if t not in calls]
    if unknown:
        raise KeyError(f"unknown target calls: {unknown}")
    deps = _edges(conn, set(calls), mode)
    in_scope = _closure(deps, targets)

    steps: list[dict] = []
    blocked: list[dict] = []
    # Dependents first: reverse execution order within the closure.
    ordered = sorted(in_scope, key=lambda c: calls[c]["seq"], reverse=True)
    for cid in ordered:
        call = calls[cid]
        if call["status"] != "executed":
            continue  # held/failed/blocked never took effect; nothing to undo
        effect, fidelity = call["effect_class"], call["fidelity_expected"]
        if effect == "irreversible" and not force:
            blocked.append({"call_id": cid, "operation": call["operation"],
                            "reason": "executed irreversible call; use force"})
            continue
        expected = EXPECTED.get((effect, fidelity), "skipped_irreversible")
        steps.append({"call_id": cid, "operation": call["operation"],
                      "seq": call["seq"], "expected": expected})

    untouched = sorted(
        cid for cid, call in calls.items()
        if cid not in in_scope and call["status"] == "executed"
    )
    status = "blocked" if blocked and not force else "ready"
    return {"status": status, "targets": targets, "mode": mode,
            "steps": steps, "blocked": blocked, "untouched": untouched}


def plan_text(plan: dict) -> str:
    """Readable rendering of a plan dict."""
    lines = [f"rollback plan ({plan['mode']}): {plan['status']}"]
    for s in plan["steps"]:
        lines.append(
            f"  - {s['operation']} [{s['call_id'][:8]}] -> {s['expected']}")
    for b in plan["blocked"]:
        lines.append(
            f"  ! BLOCKED {b['operation']} [{b['call_id'][:8]}]: {b['reason']}")
    if plan["untouched"]:
        lines.append(f"  untouched: {len(plan['untouched'])} call(s)")
    return "\n".join(lines)
