"""Static validator for proposed specs (H-062).

Rejects, with reasons: operations outside the safety blocklist, unknown
operations, template/schema violations (via the spec loader), and inverse
cycles (an operation undone by itself, or pairs undoing each other).
"""

from __future__ import annotations

from hyperion.specs import loader

from .safety import block_reason


def check_one(spec: dict,
              known_operations: set[tuple[str, str]] | None = None) -> list[str]:
    """Validate a single proposal; [] means accepted."""
    errors: list[str] = []
    for op_getter in (lambda s: s.get("operation"),
                      lambda s: (s.get("inverse") or {}).get("operation"),
                      lambda s: (s.get("before_image") or {}).get("read"),
                      lambda s: s.get("verify", {}).get("read")):
        op = op_getter(spec)
        if isinstance(op, dict) and "path" in op:
            reason = block_reason(str(op["path"]))
            if reason is not None:
                errors.append(f"blocked path {op['path']}: {reason}")
    errors.extend(loader.validate(spec, known_operations))
    fwd = spec.get("operation") or {}
    inv_spec = spec.get("inverse") or {}
    inv = inv_spec.get("operation") or {}
    if fwd and inv and fwd.get("method") == inv.get("method") \
            and fwd.get("path") == inv.get("path"):
        # Same endpoint undoing itself is only legitimate when the body
        # comes from the before-image (e.g. update restoring fields).
        # Anything else repeats the forward call.
        if not inv_spec.get("body_from_before_image"):
            errors.append("self-inverse: inverse repeats the forward call")
    return errors


def check_set(specs: dict[str, dict]) -> list[str]:
    """Detect inverse cycles across a spec set: A undone by B while B is
    undone by A (2-cycles); longer cycles cannot exist without them here
    because each spec declares exactly one inverse."""
    errors: list[str] = []
    inverse_of: dict[str, str] = {}
    for spec_id, spec in specs.items():
        inv = (spec.get("inverse") or {}).get("operation") or {}
        if inv.get("method") and inv.get("path"):
            inverse_of[spec_id] = f"{inv['method']} {inv['path']}"
    forward_of = {f"{s.get('operation', {}).get('method')} "
                  f"{s.get('operation', {}).get('path')}": sid
                  for sid, s in specs.items()}
    for spec_id, inv_key in inverse_of.items():
        other = forward_of.get(inv_key)
        if other is not None and inverse_of.get(other) == (
                f"{specs[spec_id].get('operation', {}).get('method')} "
                f"{specs[spec_id].get('operation', {}).get('path')}"):
            pair = " <-> ".join(sorted([spec_id, other]))
            if not any(pair in e for e in errors):
                errors.append(f"inverse cycle: {pair}")
    return errors
