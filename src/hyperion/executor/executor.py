"""Spec-driven executor (H-020) + approval execution (H-021).

Fail-closed throughout: unknown ops are denied/held, missing template values
and missing produced ids fail the call, and nothing prints success without a
recorded, re-readable result.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import psycopg

from hyperion.ledger import store
from hyperion.specs import loader

from . import approvals
from .clients import SystemClient

REPO_ROOT = Path(__file__).resolve().parents[3]


def default_specs_dir() -> Path:
    return REPO_ROOT / "specs"


def load_specs(specs_dir: Path | None = None) -> dict[str, dict]:
    return loader.load_dir(specs_dir or default_specs_dir())


def spec_hash(spec: dict) -> str:
    return hashlib.sha256(
        json.dumps(spec, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def lookup(obj: dict, dotted: str):
    """Dotted lookup (id, lead.id); raises KeyError when absent."""
    cur: object = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(f"missing path {dotted!r}")
        cur = cur[part]
    return cur


def resolve(value, args: dict, produced: dict | None = None):
    """Resolve a params value: literals pass through, '$.x.y' templates
    look up args/produced. Raises KeyError on missing values (fail closed)."""
    if not isinstance(value, str) or not value.startswith("$."):
        return value
    scope, _, rest = value[2:].partition(".")
    if scope == "args":
        return lookup(args, rest)
    if scope == "produced":
        if produced is None:
            raise KeyError(f"no produced values for {value!r}")
        return lookup(produced, rest)
    raise KeyError(f"unsupported template scope in {value!r}")


def resolve_params(params: dict, args: dict, produced: dict | None = None) -> dict:
    return {k: resolve(v, args, produced) for k, v in params.items()}


def _read_state(
    client: SystemClient, read: dict, args: dict, produced: dict | None = None
) -> tuple[int, object]:
    params = resolve_params(read.get("params", {}), args, produced)
    return client.request(read["method"], read["path"], params)


def _parse_explicit(operation: str) -> tuple[str, str] | None:
    parts = operation.split(None, 1)
    if len(parts) == 2 and parts[0].upper() in (
        "GET", "POST", "PUT", "PATCH", "DELETE",
    ) and parts[1].startswith("/"):
        return parts[0].upper(), parts[1]
    return None


def execute(
    conn: psycopg.Connection,
    run_id: str,
    system: str,
    operation: str,
    args: dict | None = None,
    *,
    specs: dict[str, dict] | None = None,
    clients: dict[str, SystemClient] | None = None,
    unknown: str = "deny",
    declared_deps: list[str] | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """Run one tool call through spec lookup, before-image, forward, ledger."""
    args = args or {}
    specs = specs or load_specs()
    spec_id = f"{system}.{operation}"
    spec = specs.get(spec_id)
    if spec is None:
        out = _unknown(conn, run_id, system, operation, args, unknown,
                       clients)
        if out["status"] == "held":
            _link_deps(conn, {"id": out["call_id"]}, declared_deps)
        return out
    if spec["effect_class"] == "irreversible":
        out = approvals.hold_call(
            conn, run_id, system=system, operation=operation, args=args,
            effect_class="irreversible", fidelity_expected="none",
            spec_id=spec_id, spec_hash=spec_hash(spec),
            reason="irreversible: held for approval",
        )
        _link_deps(conn, {"id": out["call_id"]}, declared_deps)
        return out
    return _run_forward(
        conn, run_id, system, operation, args, spec, spec_id,
        clients or {}, declared_deps, idempotency_key,
    )


def _unknown(conn, run_id, system, operation, args, unknown: str,
             clients: dict[str, SystemClient] | None) -> dict:
    if unknown == "hold":
        return approvals.hold_call(
            conn, run_id, system=system, operation=operation, args=args,
            effect_class="unknown", fidelity_expected="none",
            spec_id=None, spec_hash=None, reason="unknown operation: held",
        )

    if unknown == "allow_logged":
        explicit = _parse_explicit(operation)
        if explicit is None:
            return _blocked(
                conn, run_id, system, operation, args,
                "allow_logged needs an explicit 'METHOD /path' operation",
            )
        method, path = explicit
        client = (clients or {}).get(system)
        if client is None:
            return _blocked(conn, run_id, system, operation, args,
                            f"no client for system {system!r}")
        # Forwarded with no spec: no images, no inverse, fidelity none,
        # recorded honestly as unprotected.
        try:
            outcome, code, body = _forward(client, method, path, args)
        except Exception as e:
            outcome, code, body = "failed", None, None
            reason = f"transport error: {type(e).__name__}: {e}"
        else:
            reason = f"unprotected call returned {code}"
        call = store.append_call(
            conn, run_id, system=system, operation=operation, args=args,
            effect_class="unknown", fidelity_expected="none",
            status="executed" if outcome == "executed" else "failed",
            response=body if isinstance(body, dict) else None,
        )
        return {"status": outcome, "call_id": str(call["id"]),
                "reason": reason, "response": body}
    return _blocked(conn, run_id, system, operation, args, "unknown operation")


def _blocked(conn, run_id, system, operation, args, reason: str) -> dict:
    call = store.append_call(
        conn, run_id, system=system, operation=operation, args=args,
        effect_class="unknown", fidelity_expected="none", status="blocked",
    )
    return {"status": "denied", "call_id": str(call["id"]), "reason": reason}


def _forward(
    client: SystemClient, method: str, path: str, args: dict
) -> tuple[str, int | None, object]:
    """Returns (outcome, status_code, body); outcome is executed/failed."""
    status_code, body = client.request(method, path, args)
    if status_code is not None and 200 <= status_code < 300:
        return "executed", status_code, body
    return "failed", status_code, body


def _run_forward(
    conn, run_id, system, operation, args, spec, spec_id, clients,
    declared_deps, idempotency_key,
) -> dict:
    client = clients.get(system)
    if client is None:
        return _blocked(conn, run_id, system, operation, args,
                        f"no client for system {system!r}")
    op = spec["operation"]
    before_image = None
    if spec.get("before_image"):
        try:
            params = resolve_params(
                spec["before_image"]["read"].get("params", {}), args
            )
            code, body = client.request(
                spec["before_image"]["read"]["method"],
                spec["before_image"]["read"]["path"], params,
            )
        except KeyError as e:
            return _record_failure(
                conn, run_id, system, operation, args, spec, spec_id,
                f"before-image params unresolvable: {e}", declared_deps,
                idempotency_key,
            )
        if not (200 <= (code or 0) < 300) or not isinstance(body, dict):
            return _record_failure(
                conn, run_id, system, operation, args, spec, spec_id,
                f"before-image read failed (status {code})", declared_deps,
                idempotency_key,
            )
        before_image = {f: body.get(f) for f in spec["before_image"]["fields"]}

    try:
        outcome, code, body = _forward(client, op["method"], op["path"], args)
    except KeyError as e:
        return _record_failure(
            conn, run_id, system, operation, args, spec, spec_id,
            f"path params unresolvable: {e}", declared_deps, idempotency_key,
        )
    except Exception as e:  # transport error: record, never swallow silently
        return _record_failure(
            conn, run_id, system, operation, args, spec, spec_id,
            f"transport error: {type(e).__name__}: {e}", declared_deps,
            idempotency_key, before_image=before_image,
        )
    if outcome == "failed" or not isinstance(body, dict):
        return _record_failure(
            conn, run_id, system, operation, args, spec, spec_id,
            f"forward call failed (status {code})", declared_deps,
            idempotency_key, before_image=before_image, response=body,
        )

    produced: dict = {}
    try:
        for p in spec.get("produces", []):
            produced[p["name"]] = lookup({"response": body}, p["from"][2:])
    except KeyError as e:
        return _record_failure(
            conn, run_id, system, operation, args, spec, spec_id,
            f"produced id missing in response: {e}", declared_deps,
            idempotency_key, before_image=before_image, response=body,
        )

    post_image = None
    verify = spec.get("verify")
    if verify and produced:
        code, post = _read_state(client, verify["read"], args, produced)
        if isinstance(post, dict):
            post_image = post
    elif before_image is not None:
        code, post = _read_state(client, spec["before_image"]["read"], args)
        if isinstance(post, dict):
            post_image = {f: post.get(f) for f in spec["before_image"]["fields"]}

    call = store.append_call(
        conn, run_id, system=system, operation=operation, args=args,
        effect_class=spec["effect_class"],
        fidelity_expected=spec["fidelity"], status="executed",
        before_image=before_image, response=body, post_image=post_image,
        spec_id=spec_id, spec_hash=spec_hash(spec),
        idempotency_key=idempotency_key,
    )
    _link_deps(conn, call, declared_deps)
    return {"status": "executed", "call_id": str(call["id"]),
            "response": body, "produced": produced}


def _record_failure(
    conn, run_id, system, operation, args, spec, spec_id, reason,
    declared_deps, idempotency_key, before_image=None, response=None,
) -> dict:
    call = store.append_call(
        conn, run_id, system=system, operation=operation, args=args,
        effect_class=spec["effect_class"], fidelity_expected=spec["fidelity"],
        status="failed", before_image=before_image,
        response=response if isinstance(response, dict) else None,
        spec_id=spec_id, spec_hash=spec_hash(spec),
        idempotency_key=idempotency_key,
    )
    _link_deps(conn, call, declared_deps)
    return {"status": "failed", "call_id": str(call["id"]), "reason": reason}


def _link_deps(conn, call, declared_deps: list[str] | None) -> None:
    for dep in declared_deps or []:
        store.add_edge(conn, str(call["id"]), dep, "declared",
                       {"by": "caller"})


def approve_and_execute(
    conn: psycopg.Connection,
    call_id: str,
    decided_by: str,
    specs: dict[str, dict] | None,
    clients: dict[str, SystemClient],
) -> dict:
    """Approve a held call and execute it exactly once.

    Double-approve returns already_executed without re-sending.
    """
    decision = approvals.decide(conn, call_id, True, decided_by)
    if decision["status"] == "already_decided":
        call = store.get_call(conn, call_id)
        if call["status"] == "executed":
            return {"status": "already_executed", "call_id": call_id,
                    "response": call["response"]}
        return decision
    if decision["status"] != "approved":
        return decision
    call = store.get_call(conn, call_id)
    if call["status"] != "held":
        return {"status": "error",
                "reason": f"call {call_id} is {call['status']}, not held"}
    specs = specs or load_specs()
    spec_id = f"{call['system']}.{call['operation']}"
    spec = specs.get(spec_id)
    if spec is None or spec["effect_class"] != "irreversible":
        store.update_status(conn, call_id, "blocked")
        return {"status": "error", "reason": "held call has no irreversible spec"}
    client = clients.get(call["system"])
    if client is None:
        return {"status": "error",
                "reason": f"no client for system {call['system']!r}"}
    try:
        outcome, code, body = _forward(
            client, spec["operation"]["method"], spec["operation"]["path"],
            call["args"] or {},
        )
    except Exception as e:
        store.update_status(conn, call_id, "failed")
        return {"status": "failed", "call_id": call_id,
                "reason": f"transport error: {type(e).__name__}: {e}"}
    if outcome == "failed" or not isinstance(body, dict):
        store.update_status(conn, call_id, "failed")
        return {"status": "failed", "call_id": call_id,
                "reason": f"forward call failed (status {code})"}
    _finalize_held_execution(conn, call, body)
    return {"status": "executed", "call_id": call_id, "response": body}


def _finalize_held_execution(conn, call, response: dict) -> None:
    """Fill a held row's execution data and recompute its chain hash.

    Refuses when a later row already chains off the old hash (fail closed);
    approval is expected before dependents exist.
    """
    call_id = str(call["id"])
    chained = conn.execute(
        "SELECT id FROM calls WHERE prev_hash = %s", (call["entry_hash"],)
    ).fetchone()
    if chained:
        raise RuntimeError(
            f"cannot execute held call {call_id}: chained rows exist")
    conn.execute(
        "UPDATE calls SET status = 'executed', response = %s, "
        "finished_at = now() WHERE id = %s",
        (json.dumps(response), call_id),
    )
    fresh = store.get_call(conn, call_id)
    new_hash = store._hash(fresh["prev_hash"], store._payload_of(fresh))
    conn.execute(
        "UPDATE calls SET entry_hash = %s WHERE id = %s", (new_hash, call_id))
