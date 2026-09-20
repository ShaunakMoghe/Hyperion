"""C1 synthesis study (H-072): propose hold-out specs, verify live.

For each holdout op x seed: build the proposer context from the pinned
Stripe inventory (or the CRM OpenAPI, derived from the app -- never
hand-written), propose with the real LLM, validate statically, verify
against live execution, and grade.

TARGETS names which op to specify (the task statement, like a benchmark
prompt); the inverse/verify/fidelity is the answer being graded. Seeds
rotate example order: same information, isolating order effects.

Usage (from repo root):
    python bench/synth_study.py [--only stripe.products.create]
                                [--seeds 7] [--record-baseline]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench.common import (  # noqa: E402
    REPO_ROOT,
    boot_crm,
    load_dotenv_silent,
)
from targets.crm.app import create_app  # noqa: E402

from hyperion.config import load as load_config  # noqa: E402
from hyperion.executor.clients import SystemClient  # noqa: E402
from hyperion.ledger import db, store  # noqa: E402
from hyperion.specs import loader as spec_loader  # noqa: E402
from hyperion.synth import proposer, validator, verifier  # noqa: E402
from hyperion.synth.llm import BudgetTracker, make_provider  # noqa: E402
from hyperion.systems.stripe_system import StripeSystemClient  # noqa: E402

TAG = "bench-v1"
TRIALS = 2
CACHE_DIR = REPO_ROOT / "bench/cache"

# Holdout id -> (method, path, system): the task statement.
TARGETS = {
    "stripe.products.create": ("POST", "/v1/products", "stripe"),
    "stripe.coupons.create": ("POST", "/v1/coupons", "stripe"),
    "crm.notes.add": ("POST", "/deals/{deal_id}/notes", "crm"),
}


def stripe_inventory() -> tuple[dict, str]:
    data = json.loads(
        (REPO_ROOT / "studies/stripe/inventory.json").read_text(
            encoding="utf-8"))
    return data["resources"], data["spec_commit"]


def crm_inventory() -> dict:
    """Resource -> ops derived from the live FastAPI OpenAPI schema."""
    spec = create_app().openapi()
    resources: dict[str, list] = {}
    for path, methods in spec["paths"].items():
        if path.startswith(("/docs", "/openapi", "/redoc")):
            continue
        resource = path.strip("/").split("/")[0]
        for method, detail in methods.items():
            if method.upper() not in (
                    "GET", "POST", "PUT", "PATCH", "DELETE"):
                continue
            resources.setdefault(resource, []).append(
                {"method": method.upper(), "path": path,
                 "summary": (detail or {}).get("summary", "")})
    return resources


def resource_of(system: str, path: str) -> str:
    parts = [p for p in path.split("/") if p]
    if system == "stripe":
        return parts[1] if len(parts) > 1 else parts[0]
    return parts[0]


def build_context(system: str, method: str, path: str,
                  resources: dict) -> dict:
    resource = resource_of(system, path)
    entries = resources.get(resource, [])
    operation = next(e for e in entries
                     if e["method"] == method and e["path"] == path)
    siblings = [e for e in entries if e != operation]
    reads = [e for e in entries if e["method"] == "GET"]
    inverses = [e for e in entries
                if e["method"] == "DELETE"
                or (e["method"] == "POST"
                    and e["path"].rstrip("/").endswith("/cancel"))]
    return proposer.operation_context(operation, siblings, reads, inverses)


def propose_with_retry(*args, tries: int = 3, **kwargs):
    """Propose, retrying free-tier 503s with backoff (study-level)."""
    last: Exception | None = None
    for attempt in range(tries):
        try:
            return proposer.propose(*args, **kwargs)
        except Exception as e:
            last = e
            time.sleep(5 * (attempt + 1))
    raise last  # type: ignore[misc]


def tag_exists(tag: str) -> bool:
    out = subprocess.run(["git", "tag", "--list", tag], cwd=REPO_ROOT,
                         capture_output=True, text=True)
    return tag in out.stdout.split()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="C1 synthesis study")
    parser.add_argument("--only", default="",
                        help="comma-separated holdout ids")
    parser.add_argument("--seeds", default="",
                        help="comma-separated seeds (default: grid)")
    parser.add_argument("--record-baseline", action="store_true")
    args = parser.parse_args(argv)

    if args.record_baseline and not tag_exists(TAG):
        print(f"refusing: {TAG} tag missing; freeze before baselines")
        return 2

    load_dotenv_silent(REPO_ROOT / ".env")
    import os

    grid = yaml_scenarios()["synthesis_grid"]
    seeds = [int(s) for s in args.seeds.split(",")] if args.seeds \
        else list(grid["seeds"])
    targets = [t for t in TARGETS if not args.only
               or t in set(args.only.split(","))]
    if not targets or not seeds:
        print("no study items selected (check --only/--seeds)")
        return 2

    stripe_resources, spec_commit = stripe_inventory()
    crm_resources = crm_inventory()
    examples_all = proposer.load_examples(
        [REPO_ROOT / "specs/crm", REPO_ROOT / "specs/stripe"])
    provider = make_provider()
    model = os.environ.get("HYPERION_LLM_MODEL", "")
    budget = BudgetTracker()

    crm_url, server, thread = boot_crm()
    clients = {"crm": SystemClient(base_url=crm_url),
               "stripe": StripeSystemClient(os.environ["STRIPE_TEST_KEY"])}
    conn = db.connect(load_config())
    db.migrate_up(conn)
    store.create_run(conn, client="bench:synth")

    records = []
    try:
        for op_id in targets:
            method, path, system = TARGETS[op_id]
            resources = stripe_resources if system == "stripe" \
                else crm_resources
            context = build_context(system, method, path, resources)
            version = (f"stripe:{spec_commit[:12]}" if system == "stripe"
                       else "crm:app")
            commit = spec_commit if system == "stripe" else "crm-app"
            for seed in seeds:
                # Same information, rotated order (isolate order effects).
                examples = examples_all[seed % len(examples_all):] + \
                    examples_all[:seed % len(examples_all)]
                print(f"--- {op_id} seed {seed}", flush=True)
                try:
                    proposal, evidence = propose_with_retry(
                        provider, model, version, op_id, context, examples,
                        CACHE_DIR, commit, budget)
                except Exception as e:
                    records.append({"op": op_id, "seed": seed,
                                    "pass": False,
                                    "problems": [f"propose failed: {e}"]})
                    print(f"    PROPOSE-FAIL: {e}", flush=True)
                    continue
                static = validator.check_one(proposal)
                loader_errors = spec_loader.validate(proposal)
                result = {"op": op_id, "seed": seed,
                          "evidence": evidence, "static": static,
                          "loader": loader_errors}
                if static or loader_errors:
                    result["pass"] = False
                    result["problems"] = [f"static: {static + loader_errors}"]
                else:
                    verify = verifier.verify_spec(
                        clients[system], proposal, conn, model=model,
                        prompt_hash=evidence["prompt_hash"], trials=TRIALS)
                    result["verify"] = {
                        "outcome": verify["outcome"],
                        "trials": [t["outcome"] for t in verify["trials"]]}
                    ok = verify["outcome"].startswith("verified_")
                    result["pass"] = ok
                    result["problems"] = [] if ok else [
                        f"verify: {verify['outcome']}"]
                records.append(result)
                print(f"    {'PASS' if result['pass'] else 'FAIL'}: "
                      f"{result.get('problems', [])}", flush=True)
    finally:
        conn.close()
        clients["crm"].close()
        clients["stripe"].close()
        server.should_exit = True
        thread.join(timeout=15)

    passed = sum(1 for r in records if r["pass"])
    print(f"\n{passed}/{len(records)} synthesis items pass")
    print(f"budget: {budget.calls} calls, {budget.tokens} tokens, "
          f"${budget.spent_usd:.4f}")
    if args.record_baseline:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        out_path = REPO_ROOT / "bench/baselines" / f"synth-{stamp}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(
            {"tag": TAG, "records": records, "passed": passed,
             "total": len(records),
             "budget": {"calls": budget.calls, "tokens": budget.tokens,
                        "spent_usd": budget.spent_usd}}, indent=2),
            encoding="utf-8")
        print(f"baseline written to {out_path}")
    return 0 if passed == len(records) else 1


def yaml_scenarios() -> dict:
    import yaml

    return yaml.safe_load(
        (REPO_ROOT / "bench/scenarios/v1.yaml").read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
