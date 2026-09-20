"""bench-v1 freeze helper (H-070): validate scenarios, pin hashes.

Validates bench/scenarios/v1.yaml (op ids, $refs, enums, counts),
hashes every frozen input, and writes bench/scenarios/v1.freeze.json.
Refuses to overwrite an existing freeze file: post-freeze changes go
through bench/CHANGELOG.md with a reason.

The freeze file must be COMMITTED before tagging: baselines run against
the tagged commit. This script never tags (that needs explicit approval)
and never runs baselines.

Usage (from repo root): python bench/freeze.py
"""

from __future__ import annotations

import glob
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = REPO_ROOT / "bench/scenarios/v1.yaml"
FREEZE = REPO_ROOT / "bench/scenarios/v1.freeze.json"

FROZEN_FILES = [
    "bench/scenarios/v1.yaml",
    "bench/policy.yaml",
    "bench/run.py",
    "bench/synth_study.py",
    "studies/stripe/SPEC_VERSION",
    "targets/crm/migrations/001_crm.up.sql",
]

VALID_EXPECT = {"executed", "held", "failed"}
VALID_ROLLBACK = {"restored_exact", "restored_equivalent", "compensated",
                  "skipped_read", "skipped_irreversible", "conflict_detected",
                  "error"}
VALID_RB = {"clean", "compensated", "partial", "trivial", "blocked"}
VALID_RB_STATUS = {"completed", "failed"}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fail(errors: list[str]) -> None:
    print(f"freeze validation FAILED with {len(errors)} error(s):")
    for error in errors[:20]:
        print(f"  - {error}")
    sys.exit(1)


def main() -> int:
    import yaml

    errors: list[str] = []
    if FREEZE.exists():
        print(f"refusing: {FREEZE} already exists (frozen is frozen).")
        print("Post-freeze changes need a bench/CHANGELOG.md entry.")
        return 2

    doc = yaml.safe_load(SCENARIOS.read_text(encoding="utf-8"))
    tasks = doc.get("agent_tasks", [])
    if len(tasks) != 40:
        errors.append(f"want 40 tasks, found {len(tasks)}")
    ids = [t.get("id") for t in tasks]
    if len(set(ids)) != len(ids):
        errors.append("duplicate scenario ids")

    op_ids = set()
    for path in glob.glob(str(REPO_ROOT / "specs/*/*.yaml")):
        op_ids.add(yaml.safe_load(open(path).read())["id"])

    for task in tasks:
        tid = task.get("id", "?")
        system = task.get("system")
        if task.get("approvals") not in ("auto", "deny"):
            errors.append(f"{tid}: bad approvals")
        if task.get("expect_rollback") not in VALID_RB:
            errors.append(f"{tid}: bad expect_rollback")
        if task.get("expect_rb_status", "completed") not in VALID_RB_STATUS:
            errors.append(f"{tid}: bad expect_rb_status")
        for i, call in enumerate(task.get("calls", [])):
            if f"{system}.{call.get('op')}" not in op_ids:
                errors.append(f"{tid} call {i}: unknown op {call.get('op')}")

            def walk(value, call_index: int = i, tid_: str = tid,
                     i_: int = i) -> None:
                if isinstance(value, dict):
                    if set(value) == {"$ref"}:
                        index, _name = value["$ref"]
                        if not (0 <= index < call_index):
                            errors.append(f"{tid_} call {i_}: bad $ref")
                    else:
                        for item in value.values():
                            walk(item)
                elif isinstance(value, list):
                    for item in value:
                        walk(item)

            walk(call.get("args", {}))
            if call.get("expect", "executed") not in VALID_EXPECT:
                errors.append(f"{tid} call {i}: bad expect")
            if "rollback" in call and call["rollback"] not in VALID_ROLLBACK:
                errors.append(f"{tid} call {i}: bad rollback override")
            if "final" in call and call["final"] not in VALID_EXPECT:
                errors.append(f"{tid} call {i}: bad final")
            if call.get("approve") and task.get("approvals") != "auto":
                errors.append(f"{tid} call {i}: approve:true needs "
                              f"approvals auto")

    grid = doc.get("synthesis_grid", {})
    if grid.get("temperature") != 0 or not grid.get("seeds"):
        errors.append("synthesis_grid needs temperature 0 and seeds")
    if set(grid.get("holdout_ops", [])) != {
            "stripe.products.create", "stripe.coupons.create",
            "crm.notes.add"}:
        errors.append("synthesis_grid holdout_ops mismatch")

    for rel in FROZEN_FILES:
        if not (REPO_ROOT / rel).is_file():
            errors.append(f"missing frozen file: {rel}")
    if errors:
        fail(errors)

    files = {}
    for rel in FROZEN_FILES:
        files[rel] = sha256_file(REPO_ROOT / rel)
    spec_paths = sorted(glob.glob(str(REPO_ROOT / "specs/*/*.yaml")))
    digest = hashlib.sha256()
    for path in spec_paths:
        digest.update(Path(path).read_bytes())
    files["specs/*/*.yaml"] = digest.hexdigest()

    git_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True,
        text=True).stdout.strip()
    freeze = {"bench": "bench-v1", "files": files,
              "spec_files": len(spec_paths),
              "scenarios": len(tasks),
              "git_commit": git_commit}
    FREEZE.write_text(json.dumps(freeze, indent=2) + "\n", encoding="utf-8")
    print(f"validated {len(tasks)} tasks; freeze written to {FREEZE}")
    print("next: commit everything, then (with approval): "
          "git tag -a bench-v1 -m 'bench-v1 freeze'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
