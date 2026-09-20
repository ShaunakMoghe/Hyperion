"""Inverse-spec loader + validator (H-011).

Two layers: JSON Schema shape, then semantic rules (template roots,
effect_class/fidelity consistency, inverse presence, OpenAPI existence).
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ALLOWED_TEMPLATE_ROOTS = {"args", "response", "produced", "before_image"}

ALLOWED_FIDELITY = {
    "read": {"exact"},
    "reversible": {"exact", "equivalent"},
    "compensable": {"compensated"},
    "irreversible": {"none"},
}


def _schema() -> dict:
    path = Path(__file__).resolve().parent / "schema_v1.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _templates(node) -> list[str]:
    """All string values anywhere in the spec that start with '$.'."""
    found: list[str] = []
    if isinstance(node, dict):
        for v in node.values():
            found.extend(_templates(v))
    elif isinstance(node, list):
        for v in node:
            found.extend(_templates(v))
    elif isinstance(node, str) and node.startswith("$."):
        found.append(node)
    return found


def _read_ops(spec: dict) -> list[dict]:
    ops = [spec["operation"]]
    if spec.get("before_image"):
        ops.append(spec["before_image"]["read"])
    if spec.get("inverse"):
        ops.append(spec["inverse"]["operation"])
    ops.append(spec["verify"]["read"])
    return ops


def validate(
    spec: dict, known_operations: set[tuple[str, str]] | None = None
) -> list[str]:
    """Return a list of error strings; empty means valid."""
    errors: list[str] = []
    for err in sorted(
        Draft202012Validator(_schema()).iter_errors(spec), key=lambda e: list(e.path)
    ):
        errors.append(f"schema: {'/'.join(str(p) for p in err.path)}: {err.message}")
    if errors:
        return errors  # semantic checks assume the shape holds

    for t in _templates(spec):
        root = t[2:].split(".", 1)[0]
        if root not in ALLOWED_TEMPLATE_ROOTS:
            errors.append(
                f"template {t!r}: root must be one of "
                f"{sorted(ALLOWED_TEMPLATE_ROOTS)}"
            )

    effect = spec["effect_class"]
    if spec["fidelity"] not in ALLOWED_FIDELITY[effect]:
        errors.append(
            f"effect_class {effect!r} allows fidelity "
            f"{sorted(ALLOWED_FIDELITY[effect])}, got {spec['fidelity']!r}"
        )

    if effect in ("read", "irreversible"):
        if spec["inverse"] is not None:
            errors.append(f"effect_class {effect!r} must have inverse: null")
    elif spec["inverse"] is None:
        errors.append(f"effect_class {effect!r} requires an inverse operation")

    if effect in ("reversible", "compensable"):
        bi = spec.get("before_image")
        # Create-style ops (produces non-empty) have no before-image: the
        # object does not exist yet. Rollback verification for them means
        # absence-or-declared-tombstone via verify.read on the produced id.
        if not spec.get("produces") and (not bi or not bi.get("fields")):
            errors.append(
                f"effect_class {effect!r} requires before_image.fields"
            )

    for p in spec.get("produces", []):
        if not p["from"].startswith("$.response."):
            errors.append(
                f"produces {p['name']!r}: 'from' must read $.response.*"
            )

    compare = spec.get("verify", {}).get("compare", {})
    if "expect" in compare and spec.get("before_image") is not None:
        errors.append("verify.compare.expect is only for create-style specs "
                      "(before_image null)")

    if known_operations is not None:
        for op in _read_ops(spec):
            key = (op["method"].upper(), op["path"])
            if key not in known_operations:
                errors.append(f"unknown operation {key[0]} {key[1]}")
    return errors


def load_path(
    path: Path, known_operations: set[tuple[str, str]] | None = None
) -> dict:
    """Load a YAML spec file; raise ValueError with reasons if invalid."""
    spec = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    errors = validate(spec, known_operations)
    if errors:
        raise ValueError(f"{path}: invalid spec:\n" + "\n".join(errors))
    return spec


def load_dir(
    path: Path, known_operations: set[tuple[str, str]] | None = None
) -> dict[str, dict]:
    """Load every *.yaml/*.yml under path; return {spec_id: spec}."""
    out: dict[str, dict] = {}
    for f in sorted(Path(path).rglob("*.yaml")) + sorted(Path(path).rglob("*.yml")):
        spec = load_path(f, known_operations)
        if spec["id"] in out:
            raise ValueError(f"duplicate spec id {spec['id']!r} in {f}")
        out[spec["id"]] = spec
    return out
