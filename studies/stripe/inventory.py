"""Operation inventory from the pinned Stripe OpenAPI spec (H-060).

Writes studies/stripe/inventory.json: mutating operations grouped by
resource, plus excluded operations with reasons. Deterministic, no network.
Usage: python studies/stripe/inventory.py (after poe stripe-spec).
"""

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from hyperion.synth.safety import EXCLUDED_PREFIXES, resource_of  # noqa: E402

HERE = Path(__file__).resolve().parent

MUTATING = {"post", "delete", "put", "patch"}


def main() -> int:
    spec_path = HERE / "openapi.json"
    if not spec_path.is_file():
        print("openapi.json absent (run poe stripe-spec first)",
              file=sys.stderr)
        return 2
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    version = {}
    for line in (HERE / "SPEC_VERSION").read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            version[key.strip()] = value.strip()

    resources: dict[str, list] = {}
    excluded: list = []
    counts: Counter = Counter()
    for path in sorted(spec["paths"]):
        ops = spec["paths"][path]
        resource = resource_of(path)
        for method, op in sorted(ops.items()):
            if method.lower() not in MUTATING:
                continue
            counts[resource] += 1
            if resource in EXCLUDED_PREFIXES:
                excluded.append({
                    "method": method.upper(), "path": path,
                    "reason": EXCLUDED_PREFIXES[resource]})
                continue
            op_obj = op if isinstance(op, dict) else {}
            params = op_obj.get("parameters", [])
            required = sorted(p["name"] for p in params
                              if isinstance(p, dict) and p.get("required")
                              and p.get("in") == "path")
            resources.setdefault(resource, []).append({
                "method": method.upper(), "path": path,
                "operation_id": op_obj.get("operationId", ""),
                "summary": (op_obj.get("summary", "") or "")[:120],
                "required_path_params": required,
            })
    inventory = {
        "spec_commit": version.get("commit", ""),
        "mutating_operations": sum(counts.values()),
        "resources": resources,
        "resource_counts": dict(sorted(counts.items())),
        "excluded": excluded,
    }
    out = HERE / "inventory.json"
    out.write_text(json.dumps(inventory, indent=2, sort_keys=True),
                   encoding="utf-8")
    kept = sum(len(v) for v in resources.values())
    print(f"resources: {len(resources)}, kept: {kept}, "
          f"excluded: {len(excluded)}, -> inventory.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
