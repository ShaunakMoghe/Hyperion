"""Saga bench runner (M11): execute sagas, compensate, measure.

Per saga: run the ordered cross-system steps through executor/saga.py
(failed/denied steps abort and compensate), roll completed sagas back
wholesale, then measure residual damage per system. Reuses the bench-v1
residual helpers and rollback-outcome vocabulary without touching the
frozen v1 files.

Trial runs print a summary and write nothing. --record-baseline writes
bench/baselines/sagas-<ts>.json but refuses unless the sagas-v1 tag
exists: baselines are only meaningful against frozen scenarios.

Usage (from repo root):
    python bench/run_sagas.py [--only sag-01,sag-02] [--record-baseline]
                              [--skip-stripe]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml  # noqa: E402
from bench.common import REPO_ROOT, boot_crm, load_dotenv_silent  # noqa: E402
from bench.run import (  # noqa: E402
    EXPECTED_OUTCOME,
    NONCED_OPS,
    crm_residual,
    snapshot,
    stripe_residual,
    tag_exists,
)

from hyperion.config import load as load_config  # noqa: E402
from hyperion.executor import executor as ex  # noqa: E402
from hyperion.executor import rollback_exec, saga  # noqa: E402
from hyperion.executor.clients import SystemClient  # noqa: E402
from hyperion.ledger import db, store  # noqa: E402
from hyperion.systems.stripe_system import StripeSystemClient  # noqa: E402

TAG = "sagas-v1"
SCENARIOS = REPO_ROOT / "bench/scenarios/sagas.yaml"


def _policy_sha(policy: dict) -> str:
    return hashlib.sha256(json.dumps(
        policy, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def run_saga_case(conn, clients: dict, specs: dict, sg: dict) -> dict:
    """Execute one saga scenario; roll back; measure. Returns the record."""
    run_id = store.create_run(conn, client=f"saga:{sg['id']}")
    policy = sg.get("policy") or {"default": "allow", "rules": []}
    store.stamp_policy(conn, run_id, _policy_sha(policy))
    record: dict = {"id": sg["id"], "run_id": run_id, "steps": [],
                    "problems": []}
    systems = {s["system"] for s in sg["steps"]}
    pre = snapshot(clients["crm"]) if "crm" in systems else None

    steps = []
    for step in sg["steps"]:
        args = dict(step.get("args", {}))
        if step["system"] == "stripe" and step["op"] in NONCED_OPS:
            args["metadata"] = {"bench_run": run_id[:8],
                                "bench_nonce": uuid.uuid4().hex[:8],
                                "bench_scenario": sg["id"]}
        steps.append({"system": step["system"], "operation": step["op"],
                      "args": args})
    auto = sg["approvals"] == "auto"
    out = saga.run_saga(conn, run_id, steps, specs=specs, clients=clients,
                        policy=policy,
                        approve_held="auto" if auto else None)
    record["saga_status"] = out["status"]
    if out["status"] != sg["expect_saga"]:
        record["problems"].append(
            f"saga status {out['status']}, want {sg['expect_saga']}")

    produced_all: dict = {}
    call_ids: list[str] = []
    # strict=False: aborted sagas record fewer steps than scripted, and
    # steps that never ran have nothing to check.
    for i, (step, done) in enumerate(zip(sg["steps"], out["steps"],
                                         strict=False)):
        want = step.get("expect", "executed")
        entry = {"op": step["op"], "first": done["first"], "want": want,
                 "final": done["status"]}
        if "rollback" in step:
            entry["rollback"] = step["rollback"]
        if done["first"] != want:
            record["problems"].append(
                f"step {i} {step['op']}: first {done['first']}, want {want}")
        if done["first"] == "held" and auto:
            if not step.get("approve"):
                record["problems"].append(
                    f"step {i} {step['op']}: held but saga approves auto "
                    f"without approve:true")
            want_final = step.get("final", "executed")
            if done["status"] != want_final:
                record["problems"].append(
                    f"step {i} {step['op']}: approved to {done['status']}, "
                    f"want {want_final}")
        if done["status"] == "executed":
            produced_all.update(done["produced"])
            call_ids.append(done["call_id"])
            entry["call_id"] = done["call_id"]
        record["steps"].append(entry)

    # Compensation already ran on abort; completed sagas roll back now.
    if out["status"] == "completed" and call_ids:
        effects = [store.get_call(conn, c)["effect_class"] for c in call_ids]
        force = "irreversible" in effects
        rb = rollback_exec.start(conn, run_id, call_ids, clients=clients,
                                 specs=specs, force=force)
        record["rollback"] = {"status": rb["status"],
                              "outcomes": rb.get("outcomes", {}),
                              "force": force}
        outcomes = rb.get("outcomes", {})
    elif out["compensation"] is not None:
        comp = out["compensation"]
        record["rollback"] = {"status": comp["status"],
                              "outcomes": comp.get("outcomes", {}),
                              "force": "compensation"}
        outcomes = comp.get("outcomes", {})
    else:
        record["rollback"] = {"status": "nothing_to_undo"}
        outcomes = {}

    for entry in record["steps"]:
        if "call_id" not in entry or entry["call_id"] not in outcomes:
            continue
        row = store.get_call(conn, entry["call_id"])
        default_out = EXPECTED_OUTCOME.get(
            (row["effect_class"], row["fidelity_expected"]),
            "skipped_irreversible")
        want_out = entry.get("rollback", default_out)
        if outcomes[entry["call_id"]] != want_out:
            record["problems"].append(
                f"rollback {entry['op']}: outcome "
                f"{outcomes[entry['call_id']]}, want {want_out}")

    # Residual damage per system touched. Produced values decide the
    # split: CRM ids are uuids, Stripe ids carry a prefix (coupons get
    # random ids, matched by produced name instead).
    def _is_stripe(name: str, value) -> bool:
        if name == "coupon_id":
            return True
        return isinstance(value, str) and value.split("_")[0] in (
            "cus", "prod", "pi", "re")
    stripe_produced = {k: v for k, v in produced_all.items()
                       if _is_stripe(k, v)}
    crm_ids = set(produced_all.values()) - set(stripe_produced.values())
    if "crm" in systems:
        assert pre is not None
        post = snapshot(clients["crm"])
        residual = crm_residual(pre, post, crm_ids)
        record["crm_residual"] = residual
        emails = residual["emails_added"]
        want_kind = sg["expect_rollback"]
        if want_kind in ("clean", "compensated"):
            if residual["live_leftovers"] or emails:
                record["problems"].append(f"crm residual: {residual}")
        elif want_kind == "partial":
            sent = sum(1 for s in record["steps"]
                       if s["op"] == "emails.send" and "call_id" in s)
            if residual["live_leftovers"] or len(emails) != sent or not sent:
                record["problems"].append(
                    f"crm partial mismatch: {residual} (sent={sent})")
        elif want_kind in ("trivial", "blocked"):
            if residual["live_leftovers"] or emails:
                record["problems"].append(
                    f"crm {want_kind} left residue: {residual}")
    if "stripe" in systems:
        residual = stripe_residual(clients["stripe"], stripe_produced,
                                   sg["expect_rollback"])
        record["stripe_residual"] = residual
        if sg["expect_rollback"] in ("clean", "compensated",
                                      "trivial", "blocked"):
            if residual["live"]:
                record["problems"].append(
                    f"stripe residual: {residual['live']}")

    store.stamp_saga(conn, run_id, {"id": sg["id"],
                                    "status": out["status"]})
    record["pass"] = not record["problems"]
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="saga bench runner")
    parser.add_argument("--only", default="")
    parser.add_argument("--record-baseline", action="store_true")
    parser.add_argument("--skip-stripe", action="store_true")
    args = parser.parse_args(argv)
    if args.record_baseline and not tag_exists(TAG):
        print(f"refusing: tag {TAG} missing; baselines need frozen sagas.")
        return 2

    load_dotenv_silent(REPO_ROOT / ".env")
    conn = db.connect(load_config())
    db.migrate_up(conn)
    crm_url, _, _ = boot_crm()
    clients: dict = {"crm": SystemClient(base_url=crm_url)}
    key = os.environ.get("STRIPE_TEST_KEY", "")
    if key:
        clients["stripe"] = StripeSystemClient(key)
    specs = ex.load_specs()

    doc = yaml.safe_load(SCENARIOS.read_text(encoding="utf-8"))
    sagas = doc["sagas"]
    if args.only:
        want = set(args.only.split(","))
        sagas = [s for s in sagas if s["id"] in want]
    if args.skip_stripe:
        sagas = [s for s in sagas
                 if not any(st["system"] == "stripe" for st in s["steps"])]

    records = []
    try:
        for sg in sagas:
            if any(st["system"] == "stripe" for st in sg["steps"]) \
                    and "stripe" not in clients:
                print(f"{sg['id']}: SKIP (no STRIPE_TEST_KEY)")
                continue
            rec = run_saga_case(conn, clients, specs, sg)
            records.append(rec)
            mark = "PASS" if rec["pass"] else "FAIL"
            print(f"{sg['id']}: {mark} saga={rec['saga_status']}")
            for problem in rec["problems"]:
                print(f"    - {problem}")
    finally:
        clients["crm"].close()
        conn.close()

    if args.record_baseline:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        path = REPO_ROOT / "bench/baselines" / f"sagas-{stamp}.json"
        path.write_text(json.dumps(records, indent=2) + "\n",
                        encoding="utf-8")
        print(f"baseline written to {path}")
    return 0 if all(r["pass"] for r in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
