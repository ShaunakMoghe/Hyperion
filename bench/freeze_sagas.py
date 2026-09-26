"""Sagas bench freeze helper (M11): validate scenarios, pin hashes.

Validates bench/scenarios/sagas.yaml (op ids, $refs, enums, policies),
hashes every frozen input, and writes bench/scenarios/sagas.freeze.json.
Refuses to overwrite an existing freeze file: post-freeze changes go
through bench/CHANGELOG.md with a reason.

The freeze file must be COMMITTED before tagging: baselines run against
the tagged commit. This script never tags (that needs explicit approval)
and never runs baselines.

Usage (from repo root): python bench/freeze_sagas.py
"""

from __future__ import annotations

import glob
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

SCENARIOS = REPO_ROOT / "bench/scenarios/sagas.yaml"
FREEZE = REPO_ROOT / "bench/scenarios/sagas.freeze.json"

FROZEN_FILES = [
    "bench/scenarios/sagas.yaml",
    "bench/run_sagas.py",
    "studies/stripe/SPEC_VERSION",
    "targets/crm/migrations/001_crm.up.sql",
]

VALID_EXPECT = {"executed", "held", "failed", "denied"}
VALID_ROLLBACK = {"restored_exact", "restored_equivalent", "compensated",
                  "skipped_read", "skipped_irreversible", "conflict_detected",
                  "error"}
VALID_RB = {"clean", "compensated", "partial", "trivial", "blocked"}
VALID_SAGA = {"completed", "compensated", "partial"}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_sagas(doc: dict, op_ids: set[str]) -> list[str]:
    """Pure validation; returns error strings (empty means valid)."""
    from hyperion.executor import policy as policy_mod

    errors: list[str] = []
    sagas = doc.get("sagas", [])
    if len(sagas) != 6:
        errors.append(f"want 6 sagas, found {len(sagas)}")
    ids = [s.get("id") for s in sagas]
    if len(set(ids)) != len(ids):
        errors.append("duplicate saga ids")

    def walk(value, errors: list[str], tid: str, i: int,
             n_steps: int) -> None:
        if isinstance(value, dict):
            if set(value) == {"$ref"}:
                ref = value["$ref"]
                if not (isinstance(ref, list) and len(ref) == 2
                        and isinstance(ref[0], int)
                        and 0 <= ref[0] < i):
                    errors.append(f"{tid} step {i}: bad $ref")
            else:
                for item in value.values():
                    walk(item, errors, tid, i, n_steps)
        elif isinstance(value, list):
            for item in value:
                walk(item, errors, tid, i, n_steps)

    for sg in sagas:
        tid = sg.get("id", "?")
        if sg.get("approvals") not in ("auto", "deny"):
            errors.append(f"{tid}: bad approvals")
        if sg.get("expect_saga") not in VALID_SAGA:
            errors.append(f"{tid}: bad expect_saga")
        if sg.get("expect_rollback") not in VALID_RB:
            errors.append(f"{tid}: bad expect_rollback")
        policy = sg.get("policy")
        if policy is not None:
            reason = policy_mod.validate_policy(policy)
            if reason is not None:
                errors.append(f"{tid}: bad policy: {reason}")
        for i, step in enumerate(sg.get("steps", [])):
            key = f"{step.get('system')}.{step.get('op')}"
            if key not in op_ids:
                errors.append(f"{tid} step {i}: unknown op {key}")
            walk(step.get("args", {}), errors, tid, i, len(sg["steps"]))
            if step.get("expect", "executed") not in VALID_EXPECT:
                errors.append(f"{tid} step {i}: bad expect")
            if "rollback" in step and step["rollback"] not in VALID_ROLLBACK:
                errors.append(f"{tid} step {i}: bad rollback override")
            if "final" in step and step["final"] not in VALID_EXPECT:
                errors.append(f"{tid} step {i}: bad final")
            if step.get("approve") and sg.get("approvals") != "auto":
                errors.append(f"{tid} step {i}: approve:true needs "
                              f"approvals auto")
    return errors


def main() -> int:
    import yaml

    if FREEZE.exists():
        print(f"refusing: {FREEZE} already exists (frozen is frozen).")
        print("Post-freeze changes need a bench/CHANGELOG.md entry.")
        return 2

    doc = yaml.safe_load(SCENARIOS.read_text(encoding="utf-8"))
    op_ids = set()
    for path in glob.glob(str(REPO_ROOT / "specs/*/*.yaml")):
        op_ids.add(yaml.safe_load(open(path).read())["id"])
    errors = validate_sagas(doc, op_ids)
    for rel in FROZEN_FILES:
        if not (REPO_ROOT / rel).is_file():
            errors.append(f"missing frozen file: {rel}")
    if errors:
        print(f"freeze validation FAILED with {len(errors)} error(s):")
        for error in errors[:20]:
            print(f"  - {error}")
        return 1

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
    freeze = {"bench": "sagas-v1", "files": files,
              "spec_files": len(spec_paths),
              "sagas": len(doc["sagas"]),
              "git_commit": git_commit}
    FREEZE.write_text(json.dumps(freeze, indent=2) + "\n", encoding="utf-8",
                       newline="\n")
    print(f"validated {len(doc['sagas'])} sagas; freeze written to {FREEZE}")
    print("next: commit everything, then (with approval): "
          "git tag -a sagas-v1 -m 'sagas-v1 freeze'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
