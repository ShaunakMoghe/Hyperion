"""Inverse verification harness (H-063): sandbox truth for proposals.

Per operation: build fixtures in test mode, snapshot the before-image, run
the forward call, run the inverse, re-read, compare per declared fidelity.
N trials (default 3) for flakiness. Outcomes: verified_exact,
verified_equivalent, verified_compensated, failed_inverse, state_mismatch,
fixture_unavailable, unsafe_blocked. Irreversible specs are never
auto-executed (recorded as skipped_held). Isolated per trial with unique
objects; best-effort cleanup; refuses non-test credentials via StripeClient.
"""

from __future__ import annotations

import json
import uuid

import psycopg

from hyperion.executor import executor as ex
from hyperion.executor import rollback_exec
from hyperion.executor.clients import fill_path
from hyperion.synth import validator

SKIPPED_HELD = "skipped_held"


def unique_tag() -> dict:
    return {"hyperion_verify": uuid.uuid4().hex[:8]}


def _fixture_post_customers(_client, _spec) -> dict:
    return {"name": "Verify", "email": "verify@example.com",
            "metadata": unique_tag()}


def _fixture_update_customers(client, _spec) -> dict:
    # NOTE: the fixture sets every restored field (name AND email).
    # Restoring a field that was null at before-time (email unset) is a
    # known Stripe edge (None encodes as empty, not null); the study
    # records it rather than pretending restores are total.
    code, body = client.request("POST", "/v1/customers",
                                {"name": "Pre", "email": "pre@example.com",
                                 "metadata": unique_tag()})
    if code != 200:
        raise RuntimeError(f"fixture customer failed: {code}")
    return {"customer": body["id"], "name": "Post",
            "email": "post@example.com"}


def _fixture_simple(args: dict):
    def build(_client, _spec) -> dict:
        merged = dict(args)
        merged["metadata"] = unique_tag()
        return merged
    return build


def _fixture_create_pi(client, _spec) -> dict:
    return {"amount": 200, "currency": "usd", "metadata": unique_tag()}


def _fixture_confirm_pi(client, _spec) -> dict:
    code, body = client.request("POST", "/v1/payment_intents", {
        "amount": 200, "currency": "usd", "metadata": unique_tag(),
        "automatic_payment_methods": {"enabled": True,
                                      "allow_redirects": "never"}})
    if code != 200:
        raise RuntimeError(f"fixture PI failed: {code}")
    return {"intent": body["id"], "payment_method": "pm_card_visa"}


def _fixture_cancel_pi(client, _spec) -> dict:
    code, body = client.request("POST", "/v1/payment_intents",
                                {"amount": 200, "currency": "usd",
                                 "metadata": unique_tag()})
    if code != 200:
        raise RuntimeError(f"fixture PI failed: {code}")
    return {"intent": body["id"]}


def _fixture_refund(client, _spec) -> dict:
    args = _fixture_confirm_pi(client, _spec)
    code, _ = client.request(
        "POST", f"/v1/payment_intents/{args['intent']}/confirm",
        {"payment_method": args["payment_method"]})
    if code != 200:
        raise RuntimeError(f"fixture confirm failed: {code}")
    return {"payment_intent": args["intent"]}


FIXTURES = {
    ("POST", "/v1/customers"): _fixture_post_customers,
    ("POST", "/v1/customers/{customer}"): _fixture_update_customers,
    ("POST", "/v1/products"): _fixture_simple({"name": "Verify product"}),
    ("POST", "/v1/coupons"): _fixture_simple(
        {"percent_off": 10, "duration": "once"}),
    ("POST", "/v1/payment_intents"): _fixture_create_pi,
    ("POST", "/v1/payment_intents/{intent}/confirm"): _fixture_confirm_pi,
    ("POST", "/v1/payment_intents/{intent}/cancel"): _fixture_cancel_pi,
    ("POST", "/v1/refunds"): _fixture_refund,
}


_CANCELABLE_PI = {"requires_payment_method", "requires_confirmation",
                    "requires_capture"}


def _cancel_pi_if_open(client, intent: str, problems: list) -> None:
    """Cancel a fixture PaymentIntent left uncaptured; quiet when the trial
    already moved it on (confirmed/refunded), notes only real failures."""
    try:
        filled, _ = fill_path("/v1/payment_intents/{intent}",
                              {"intent": intent})
        code, body = client.request("GET", filled, {})
    except Exception as e:  # cleanup must never fail the trial
        problems.append(f"GET {filled}: {type(e).__name__}")
        return
    if code != 200 or not isinstance(body, dict):
        return
    if body.get("status") not in _CANCELABLE_PI:
        return
    try:
        filled, _ = fill_path("/v1/payment_intents/{intent}/cancel",
                              {"intent": intent})
        code, _ = client.request("POST", filled, {})
        if code not in (200, 404):
            problems.append(f"POST {filled}: {code}")
    except Exception as e:
        problems.append(f"POST {filled}: {type(e).__name__}")


def _cleanup(client, spec: dict, produced: dict, args: dict) -> list[str]:
    """Best-effort removal of trial objects; returns failure notes.

    Covers fixture-built objects too: the update fixture's customer lives
    in args (not produced), and PI fixtures leave uncaptured intents when
    a trial fails before its inverse runs.
    """
    problems = []
    spec_id = spec.get("id", "")
    handlers = {
        "stripe.customers.create": [
            ("DELETE", "/v1/customers/{customer}",
             {"customer": produced.get("customer_id")})],
        "stripe.customers.update": [
            ("DELETE", "/v1/customers/{customer}",
             {"customer": args.get("customer")})],
        "stripe.products.create": [
            ("DELETE", "/v1/products/{id}",
             {"id": produced.get("product_id")})],
        "stripe.coupons.create": [
            ("DELETE", "/v1/coupons/{coupon}",
             {"coupon": produced.get("coupon_id")})],
    }
    for method, path, params in handlers.get(spec_id, []):
        if any(v is None for v in params.values()):
            continue
        try:
            filled, _ = fill_path(path, params)
            code, _ = client.request(method, filled, {})
            if code not in (200, 404):
                problems.append(f"{method} {filled}: {code}")
        except Exception as e:  # cleanup must never fail the trial
            problems.append(f"{method} {path}: {type(e).__name__}")
    if spec_id in ("stripe.payment_intents.confirm",
                   "stripe.payment_intents.cancel",
                   "stripe.refunds.create"):
        # The refund fixture keys the intent as payment_intent. Confirmed
        # PIs are never touched here (only the trial inverse may refund);
        # the status gate inside _cancel_pi_if_open enforces that.
        intent = (args.get("intent") or args.get("payment_intent")
                  or produced.get("payment_intent_id"))
        if intent is not None:
            _cancel_pi_if_open(client, intent, problems)
    return problems


def _read(client, read: dict, args: dict,
          produced: dict | None) -> tuple[int | None, object]:
    try:
        params = ex.resolve_params(read.get("params", {}), args,
                                   produced or None)
        return client.request(read["method"], read["path"], params)
    except Exception as e:  # transport failure reads as absent
        return None, {"error": f"{type(e).__name__}"}


def run_trial(client, spec: dict, trial_no: int = 0) -> dict:
    """One forward/inverse/verify cycle. Returns {outcome, evidence}.

    Fixture-built objects are always removed: the attempt runs under
    try/finally, so every early return still cleans up what the fixture
    and the forward call created.
    """
    op = spec["operation"]
    key = (op["method"].upper(), op["path"])
    factory = FIXTURES.get(key)
    if factory is None:
        return {"outcome": "fixture_unavailable",
                "evidence": {"reason": f"no fixture for {key}"}}
    try:
        result, args, produced = _attempt(client, spec, factory)
    except Exception as e:  # defensive: _attempt returns on all paths
        result, args, produced = (
            {"outcome": "error",
             "evidence": {"reason": f"trial crashed: {e}"}}, {}, {})
    finally:
        notes = _cleanup(client, spec, produced, args)
    result.setdefault("evidence", {}).setdefault("cleanup", notes)
    return result


def _attempt(client, spec: dict, factory) -> tuple[dict, dict, dict]:
    """Trial body; returns (result, args, produced) for cleanup."""
    try:
        args = factory(client, spec)
    except Exception as e:
        return ({"outcome": "fixture_unavailable",
                 "evidence": {"reason": f"fixture failed: {e}"}}, {}, {})

    before = None
    if spec.get("before_image"):
        code, body = _read(client, spec["before_image"]["read"], args, None)
        if code is None or not 200 <= code < 300 \
                or not isinstance(body, dict):
            return ({"outcome": "fixture_unavailable",
                     "evidence": {"reason": f"before-image read: {code}"}},
                    args, {})
        before = {f: body.get(f) for f in spec["before_image"]["fields"]}

    op = spec["operation"]
    try:
        fwd_code, fwd_body = client.request(op["method"], op["path"], args)
    except Exception as e:
        return ({"outcome": "fixture_unavailable",
                 "evidence": {
                     "reason": f"forward raised: {type(e).__name__}"}},
                args, {})
    if not 200 <= (fwd_code or 0) < 300 or not isinstance(fwd_body, dict):
        return ({"outcome": "fixture_unavailable",
                 "evidence": {"reason": f"forward: {fwd_code}"}}, args, {})
    try:
        produced = {p["name"]: ex.lookup({"response": fwd_body}, p["from"][2:])
                    for p in spec.get("produces", [])}
    except KeyError as e:
        return ({"outcome": "state_mismatch",
                 "evidence": {"reason": f"produced id missing: {e}"}},
                args, {})

    inv = spec["inverse"]
    try:
        params = ex.resolve_params(inv.get("params", {}), args,
                                   produced or None)
        body = {}
        for fname in inv.get("body_from_before_image", []):
            if not isinstance(before, dict) or fname not in before:
                raise KeyError(fname)
            body[fname] = before[fname]
        filled, rest = fill_path(inv["operation"]["path"], params)
        method = inv["operation"]["method"]
        if method.upper() in ("POST", "PUT", "PATCH"):
            inv_code, _ = client.request(method, filled, {**rest, **body})
        else:
            inv_code, _ = client.request(method, filled, {})
    except KeyError as e:
        return ({"outcome": "state_mismatch",
                 "evidence": {"reason": f"inverse unresolvable: {e}"}},
                args, produced)
    except Exception as e:
        return ({"outcome": "failed_inverse",
                 "evidence": {
                     "reason": f"inverse raised: {type(e).__name__}"}},
                args, produced)
    if not 200 <= (inv_code or 0) < 300:
        if inv_code in (404, 410):
            pass  # possibly already undone; verify decides
        else:
            return ({"outcome": "failed_inverse",
                     "evidence": {"inverse_status": inv_code}},
                    args, produced)

    outcome, fidelity = rollback_exec._verify(client, spec, args,
                                              produced or None, before)
    evidence = {"forward_status": fwd_code, "inverse_status": inv_code}
    if outcome in ("restored_exact", "restored_equivalent", "compensated"):
        return ({"outcome": f"verified_{fidelity}", "evidence": evidence},
                args, produced)
    evidence["reason"] = "post-inverse state mismatch"
    return ({"outcome": "state_mismatch", "evidence": evidence},
            args, produced)


def verify_spec(client, spec: dict, conn: psycopg.Connection | None = None,
                model: str = "human", prompt_hash: str = "",
                trials: int = 3) -> dict:
    """Run N trials; persist trial rows when conn is given."""
    if spec.get("effect_class") == "irreversible":
        return {"spec_id": spec.get("id"), "outcome": SKIPPED_HELD,
                "trials": [], "evidence": {
                    "reason": "held for approval; never auto-executed"}}
    static_errors = validator.check_one(spec)
    if static_errors:
        return {"spec_id": spec.get("id"), "outcome": "unsafe_blocked",
                "trials": [], "evidence": {"static": static_errors}}
    if conn is not None:
        # Idempotent re-runs: one row per (spec, model, prompt, trial).
        conn.execute(
            "DELETE FROM verification_trials WHERE spec_id = %s AND model = %s"
            " AND prompt_hash = %s",
            (spec.get("id"), model, prompt_hash))
    results = []
    for trial_no in range(trials):
        result = run_trial(client, spec, trial_no)
        result["trial_no"] = trial_no
        results.append(result)
        if conn is not None:
            conn.execute(
                """INSERT INTO verification_trials
                   (id, spec_id, model, prompt_hash, trial_no, outcome,
                    evidence)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (str(uuid.uuid4()), spec.get("id"), model, prompt_hash,
                 trial_no, result["outcome"],
                 json.dumps(result["evidence"])))
    outcomes = [r["outcome"] for r in results]
    agreed = outcomes[0] if all(o == outcomes[0] for o in outcomes) else "mixed"
    return {"spec_id": spec.get("id"), "outcome": agreed,
            "trials": results,
            "evidence": {"outcomes": outcomes}}
