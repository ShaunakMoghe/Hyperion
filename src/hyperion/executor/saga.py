"""Cross-system saga runner (M11): ordered steps with compensation.

A saga is a list of tool calls that may span systems. Steps run in order;
the first failed or denied step aborts the saga and compensates every
completed step in reverse dependency order (via the rollback engine).
Held steps pause the saga for a human unless approve_held="auto".

Saga status:
- completed: every step executed. Nothing was compensated.
- compensated: aborted, and every completed step restored or payed back.
- partial: aborted, compensation ran but something is left behind
  (irreversible effects, conflicts, errors).
- failed: aborted and compensation itself could not run.
- awaiting_approval: paused on a held step (approve_held unset).

Step args may carry {"$ref": [step_index, produced_name]} leaves, resolved
from earlier steps' produced values (same shape as the bench call scripts).
Outcomes reuse the rollback vocabulary, so saga verdicts are comparable
with bench rollback expectations.
"""

from __future__ import annotations

import psycopg

from hyperion.executor import executor as ex
from hyperion.executor import rollback_exec
from hyperion.executor.clients import SystemClient

# Rollback outcomes that leave nothing behind.
RESTORED = {"restored_exact", "restored_equivalent", "compensated",
            "skipped_read"}


def resolve_refs(value, produced_by_index: list[dict]):
    """Resolve {"$ref": [step_index, produced_name]} leaves recursively."""
    if isinstance(value, dict):
        if set(value) == {"$ref"}:
            index, name = value["$ref"]
            return produced_by_index[index][name]
        return {k: resolve_refs(v, produced_by_index)
                for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_refs(v, produced_by_index) for v in value]
    return value


def run_saga(
    conn: psycopg.Connection,
    run_id: str,
    steps: list[dict],
    *,
    specs: dict[str, dict] | None = None,
    clients: dict[str, SystemClient] | None = None,
    policy: dict | None = None,
    mode: str = "provenance",
    approve_held: str | None = None,
) -> dict:
    """Run saga steps; compensate on abort. Never raises on step outcomes.

    Each step is {system, operation, args} with optional $refs. Returns
    {status, steps, compensation}: per-step {call_id, first, status,
    produced} (first = pre-approval status) plus the rollback result when
    compensation ran (else None).
    """
    specs = specs or ex.load_specs()
    done: list[dict] = []
    produced_by_index: list[dict] = []
    for index, step in enumerate(steps):
        args = resolve_refs(dict(step.get("args") or {}), produced_by_index)
        out = ex.execute(
            conn, run_id, step["system"], step["operation"], args,
            specs=specs, clients=clients, policy=policy,
        )
        first = out["status"]
        if first == "held" and approve_held == "auto":
            out = ex.approve_and_execute(conn, out["call_id"], "saga:auto",
                                         specs, clients or {})
        spec = specs.get(f"{step['system']}.{step['operation']}", {})
        produced = out.get("produced") or {}
        record = {"call_id": out.get("call_id"), "first": first,
                  "status": out["status"], "produced": produced,
                  "effect_class": spec.get("effect_class", "unknown")}
        done.append(record)
        produced_by_index.append(produced)
        if out["status"] == "executed":
            continue
        if out["status"] == "held":
            return {"status": "awaiting_approval", "steps": done,
                    "compensation": None, "aborted_at": index}
        return _abort(conn, run_id, done, index, mode, clients, specs)
    return {"status": "completed", "steps": done, "compensation": None,
            "aborted_at": None}


def _abort(conn, run_id, done, index, mode, clients, specs) -> dict:
    completed = [s for s in done[:index]
                 if s["status"] == "executed" and s["call_id"]]
    # Mirror the bench: force only when an irreversible is in scope, so
    # its step reports skipped_irreversible instead of blocking the plan.
    force = any(s["effect_class"] == "irreversible" for s in completed)
    compensation = rollback_exec.start(
        conn, run_id, [s["call_id"] for s in completed], mode=mode,
        force=force, clients=clients, specs=specs)
    if compensation["status"] != "completed":
        return {"status": "failed", "steps": done,
                "compensation": compensation, "aborted_at": index}
    outcomes = list(compensation.get("outcomes", {}).values())
    status = "compensated" if all(o in RESTORED for o in outcomes) else "partial"
    return {"status": status, "steps": done, "compensation": compensation,
            "aborted_at": index}
