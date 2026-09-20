"""bench-v1 agent-task runner (H-071): execute, roll back, measure.

Per scenario: run the fixed call script through the spec executor with
bench/policy.yaml, approve held calls per the scenario preset, roll back,
then measure residual damage (live leftovers, not declared terminal
states like tombstones or canceled intents).

Trial runs print a summary and write nothing. --record-baseline writes
bench/baselines/<ts>.json but refuses unless the bench-v1 tag exists:
baselines are only meaningful against frozen scenarios.

Usage (from repo root):
    python bench/run.py [--only crm-01,str-05] [--record-baseline]
                        [--skip-stripe] [--skip-crm]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml  # noqa: E402
from bench.common import REPO_ROOT, boot_crm, load_dotenv_silent  # noqa: E402

from hyperion.config import load as load_config  # noqa: E402
from hyperion.executor import executor, rollback_exec  # noqa: E402
from hyperion.executor import policy as policy_mod  # noqa: E402
from hyperion.executor.clients import SystemClient  # noqa: E402
from hyperion.ledger import db, store  # noqa: E402
from hyperion.systems.stripe_system import StripeSystemClient  # noqa: E402

TAG = "bench-v1"

# Stripe creates get a unique metadata nonce per call (shared values would
# false-link provenance). Updates stay scalar-only: Stripe merges metadata
# maps, which is not exactly restorable.
NONCED_OPS = {"customers.create", "products.create", "coupons.create",
              "payment_intents.create"}


def resolve_refs(value, produced_by_index: list[dict]):
    """Resolve {"$ref": [call_index, produced_name]} recursively."""
    if isinstance(value, dict):
        if set(value) == {"$ref"}:
            index, name = value["$ref"]
            return produced_by_index[index][name]
        return {k: resolve_refs(v, produced_by_index) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_refs(v, produced_by_index) for v in value]
    return value


def snapshot(crm: SystemClient) -> dict:
    code, body = crm.request("GET", "/snapshot", {})
    assert code == 200, f"snapshot failed: {code}"
    return body


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      default=str)


def crm_residual(pre: dict, post: dict, produced_ids: set[str]) -> dict:
    """Live leftovers after rollback. Tombstoned scenario rows and exact
    matches are expected; anything else is damage."""
    leftovers: list[str] = []
    for table, rows in post.items():
        if table == "emails_outbox":
            continue
        before = {r["id"]: r for r in pre.get(table, [])}
        for row in rows:
            rid = row["id"]
            if rid not in before:
                if rid in produced_ids and row.get("deleted_at") is not None:
                    continue  # expected tombstone of a scenario object
                leftovers.append(f"{table}:{rid}: unexpected new row")
            elif canonical(row) != canonical(before[rid]):
                leftovers.append(f"{table}:{rid}: modified pre-existing row")
    for table, rows in pre.items():
        if table == "emails_outbox":
            continue
        after = {r["id"] for r in post.get(table, [])}
        for row in rows:
            if row["id"] not in after:
                leftovers.append(f"{table}:{row['id']}: pre-existing row gone")
    pre_mails = {r["id"] for r in pre.get("emails_outbox", [])}
    mails_added = [r["id"] for r in post.get("emails_outbox", [])
                   if r["id"] not in pre_mails]
    return {"live_leftovers": leftovers, "emails_added": mails_added}


def stripe_residual(client: StripeSystemClient, produced: dict,
                    expect_rollback: str) -> dict:
    """Re-read every produced object; anything live is damage. Terminal
    states (deleted/canceled/succeeded+refunded) are expected."""
    live: list[str] = []
    checked: list[str] = []
    for name, obj_id in produced.items():
        if name == "customer_id":
            code, body = client.request(
                "GET", "/v1/customers/{customer}", {"customer": obj_id})
            checked.append(f"customer:{obj_id}:{code}")
            if not (code == 200 and body.get("deleted") is True):
                live.append(f"customer:{obj_id}: still live ({code})")
        elif name == "product_id":
            code, _ = client.request("GET", f"/v1/products/{obj_id}", {})
            checked.append(f"product:{obj_id}:{code}")
            if code != 404:
                live.append(f"product:{obj_id}: still live ({code})")
        elif name == "coupon_id":
            code, _ = client.request("GET", f"/v1/coupons/{obj_id}", {})
            checked.append(f"coupon:{obj_id}:{code}")
            if code != 404:
                live.append(f"coupon:{obj_id}: still live ({code})")
        elif name == "payment_intent_id":
            code, body = client.request(
                "GET", "/v1/payment_intents/{intent}", {"intent": obj_id})
            status = body.get("status") if isinstance(body, dict) else None
            checked.append(f"pi:{obj_id}:{status}")
            if expect_rollback == "compensated":
                if status != "succeeded":
                    live.append(f"pi:{obj_id}: expected succeeded, "
                                f"got {status}")
                else:
                    _r, refunds = client.request(
                        "GET", "/v1/refunds",
                        {"payment_intent": obj_id})
                    data = refunds.get("data", []) \
                        if isinstance(refunds, dict) else []
                    if not data:
                        live.append(f"pi:{obj_id}: no refund found")
            else:
                if status != "canceled":
                    live.append(f"pi:{obj_id}: expected canceled, "
                                f"got {status}")
        elif name == "refund_id":
            code, body = client.request(
                "GET", "/v1/refunds/{refund}", {"refund": obj_id})
            status = body.get("status") if isinstance(body, dict) else None
            checked.append(f"refund:{obj_id}:{status}")
            if status != "succeeded":
                live.append(f"refund:{obj_id}: unexpected {status}")
    return {"checked": checked, "live": live}


EXPECTED_OUTCOME = {
    ("reversible", "exact"): "restored_exact",
    ("reversible", "equivalent"): "restored_equivalent",
    ("compensable", "compensated"): "compensated",
    ("read", "exact"): "skipped_read",
}


def run_scenario(conn, run_id: str, scenario: dict, clients: dict,
                 specs: dict, policy: dict) -> dict:
    """Execute the call script, roll back, measure. Returns the record."""
    system = scenario["system"]
    auto = scenario["approvals"] == "auto"
    record: dict = {"id": scenario["id"], "calls": [], "problems": []}
    produced_by_index: list[dict] = []
    produced_all: dict = {}
    call_ids: list[str] = []

    pre = snapshot(clients["crm"]) if system == "crm" else None

    prev_call: str | None = None
    for i, call in enumerate(scenario["calls"]):
        op = call["op"]
        args = resolve_refs(dict(call.get("args", {})), produced_by_index)
        if system == "stripe" and op in NONCED_OPS:
            args["metadata"] = {"bench_run": run_id[:8],
                                "bench_nonce": uuid.uuid4().hex[:8],
                                "bench_scenario": scenario["id"]}
        out = executor.execute(
            conn, run_id, system, op, args, specs=specs, clients=clients,
            policy=policy,
            declared_deps=[prev_call] if prev_call else None)
        first = out["status"]
        want = call.get("expect", "executed")
        entry = {"op": op, "first": first, "want": want}
        if "rollback" in call:
            entry["rollback"] = call["rollback"]
        if first != want:
            record["problems"].append(
                f"call {i} {op}: first status {first}, want {want} "
                f"({out.get('reason', '')})")
        final = first
        if first == "held" and auto and call.get("approve"):
            approved = executor.approve_and_execute(
                conn, out["call_id"], "bench:auto", specs, clients)
            final = approved["status"]
            entry["approved_final"] = final
            want_final = call.get("final", "executed")
            if final != want_final:
                record["problems"].append(
                    f"call {i} {op}: approved to {final}, want {want_final} "
                    f"({approved.get('reason', '')})")
            if final == "executed":
                row = store.get_call(conn, out["call_id"])
                made = _produced_of(specs[f"{system}.{op}"],
                                    row["response"])
                produced_by_index.append(made)
                produced_all.update(made)
                call_ids.append(out["call_id"])
                prev_call = out["call_id"]
                entry["call_id"] = out["call_id"]
                record["calls"].append(entry)
                continue
        elif first == "held" and auto and not call.get("approve"):
            record["problems"].append(
                f"call {i} {op}: held but scenario approves auto without "
                f"approve:true")
        if first == "executed":
            produced_by_index.append(out.get("produced", {}))
            produced_all.update(out.get("produced", {}))
            call_ids.append(out["call_id"])
            prev_call = out["call_id"]
            entry["call_id"] = out["call_id"]
        else:
            produced_by_index.append({})
        record["calls"].append(entry)

    record["produced"] = produced_all
    executed = [c for c in record["calls"] if "call_id" in c]

    # Roll back when anything took effect.
    if executed:
        effects = [store.get_call(conn, c["call_id"])["effect_class"]
                   for c in executed]
        force = "irreversible" in effects
        rb = rollback_exec.start(conn, run_id, [c["call_id"] for c in executed],
                                 clients=clients, specs=specs, force=force)
        record["rollback"] = {"status": rb["status"],
                              "outcomes": rb.get("outcomes", {}),
                              "force": force}
        want_status = scenario.get("expect_rb_status", "completed")
        if rb["status"] != want_status:
            record["problems"].append(
                f"rollback status {rb['status']}, want {want_status}: {rb}")
        for entry in executed:
            row = store.get_call(conn, entry["call_id"])
            default_out = EXPECTED_OUTCOME.get(
                (row["effect_class"], row["fidelity_expected"]),
                "skipped_irreversible")
            want_out = entry.get("rollback", default_out)
            got = rb.get("outcomes", {}).get(entry["call_id"])
            if got != want_out:
                record["problems"].append(
                    f"rollback {entry['op']}: outcome {got}, "
                    f"want {want_out}")
    else:
        record["rollback"] = {"status": "nothing_to_undo"}

    # Residual damage.
    if system == "crm":
        assert pre is not None
        post = snapshot(clients["crm"])
        produced_ids = set(produced_all.values())
        residual = crm_residual(pre, post, produced_ids)
        record["residual"] = residual
        emails = residual["emails_added"]
        want_kind = scenario["expect_rollback"]
        if want_kind in ("clean", "compensated"):
            if residual["live_leftovers"] or emails:
                record["problems"].append(f"residual damage: {residual}")
        elif want_kind == "partial":
            sent = sum(1 for c in executed if c["op"] == "emails.send")
            if residual["live_leftovers"] or len(emails) != sent or not sent:
                record["problems"].append(
                    f"partial mismatch: {residual} (sent={sent})")
        elif want_kind in ("trivial", "blocked"):
            if residual["live_leftovers"] or emails:
                record["problems"].append(
                    f"{want_kind} scenario left residue: {residual}")
    else:
        residual = stripe_residual(clients["stripe"], produced_all,
                                   scenario["expect_rollback"])
        record["residual"] = residual
        if scenario["expect_rollback"] in ("clean", "compensated",
                                           "trivial", "blocked"):
            if residual["live"]:
                record["problems"].append(
                    f"residual damage: {residual['live']}")

    record["pass"] = not record["problems"]
    return record


def _produced_of(spec: dict, response: dict | None) -> dict:
    """Recompute produced ids from a ledgered response (approved calls)."""
    out: dict = {}
    if not isinstance(response, dict):
        return out
    for p in spec.get("produces", []):
        try:
            out[p["name"]] = executor.lookup({"response": response},
                                             p["from"][2:])
        except KeyError:
            continue
    return out


def tag_exists(tag: str) -> bool:
    out = subprocess.run(["git", "tag", "--list", tag], cwd=REPO_ROOT,
                         capture_output=True, text=True)
    return tag in out.stdout.split()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="bench-v1 agent-task runner")
    parser.add_argument("--scenarios", default="bench/scenarios/v1.yaml")
    parser.add_argument("--only", default="",
                        help="comma-separated scenario ids")
    parser.add_argument("--record-baseline", action="store_true")
    parser.add_argument("--skip-stripe", action="store_true")
    parser.add_argument("--skip-crm", action="store_true")
    args = parser.parse_args(argv)

    if args.record_baseline and not tag_exists(TAG):
        print(f"refusing: {TAG} tag missing; freeze before baselines")
        return 2

    load_dotenv_silent(REPO_ROOT / ".env")
    import os

    doc = yaml.safe_load(
        (REPO_ROOT / args.scenarios).read_text(encoding="utf-8"))
    tasks = doc["agent_tasks"]
    if args.only:
        wanted = set(args.only.split(","))
        tasks = [t for t in tasks if t["id"] in wanted]
    if not tasks:
        print("no scenarios selected (check --only)")
        return 2

    policy, error = policy_mod.load_policy(REPO_ROOT / "bench/policy.yaml")
    assert error is None, error

    crm_url, server, thread = boot_crm()
    clients: dict = {"crm": SystemClient(base_url=crm_url)}
    if not args.skip_stripe:
        key = os.environ.get("STRIPE_TEST_KEY", "")
        assert key.startswith(("sk_test_", "rk_test_")), "bad/missing key"
        clients["stripe"] = StripeSystemClient(key)
    specs = executor.load_specs()
    conn = db.connect(load_config())

    records = []
    try:
        for task in tasks:
            if task["system"] == "stripe" and args.skip_stripe:
                continue
            if task["system"] == "crm" and args.skip_crm:
                continue
            run_id = store.create_run(conn, client=f"bench:{task['id']}")
            print(f"--- {task['id']}: {task['task']}", flush=True)
            try:
                record = run_scenario(conn, run_id, task, clients, specs,
                                      policy)
            except Exception as e:  # never lose the baseline to a crash
                record = {"id": task["id"], "pass": False,
                          "problems": [f"runner crash: {type(e).__name__}: "
                                       f"{e}"]}
            records.append(record)
            print(f"    {'PASS' if record['pass'] else 'FAIL'}: "
                  f"{record.get('problems', [])}", flush=True)
    finally:
        conn.close()
        clients["crm"].close()
        if "stripe" in clients:
            clients["stripe"].close()
        server.should_exit = True
        thread.join(timeout=15)

    passed = sum(1 for r in records if r["pass"])
    print(f"\n{passed}/{len(records)} scenarios pass")
    if args.record_baseline:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        out_path = REPO_ROOT / "bench/baselines" / f"{stamp}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"scenarios": args.scenarios, "tag": TAG,
                   "records": records,
                   "passed": passed, "total": len(records)}
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"baseline written to {out_path}")
    return 0 if passed == len(records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
