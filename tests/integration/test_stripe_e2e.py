"""H-033: Stripe test-mode e2e (marker `stripe`; skipped without key).

Real test-mode calls -> fault -> rollback -> verify by re-reading.
Cleans up every object it creates. No mocks.
"""

import os
import uuid

import pytest

from hyperion.executor import executor, rollback_exec
from hyperion.ledger import db, store
from hyperion.systems.stripe_system import StripeSystemClient

pytestmark = pytest.mark.stripe


def _clients():
    key = os.environ["STRIPE_TEST_KEY"]
    assert key.startswith(("sk_test_", "rk_test_"))
    return {"stripe": StripeSystemClient(key)}


def _env():
    conn = db.connect()
    db.migrate_up(conn)
    run_id = store.create_run(conn, client="stripe-e2e")
    return conn, run_id, _clients(), executor.load_specs()


def _tag():
    return {"hyperion_e2e": uuid.uuid4().hex[:8]}


def test_stripe_rollback_e2e():
    conn, run_id, clients, specs = _env()
    try:
        # NOTE: each object gets a distinct metadata nonce. A shared value
        # would legitimately (if falsely) link every call to every other
        # call through provenance -- the approximation limit from H-050.
        cust = executor.execute(
            conn, run_id, "stripe", "customers.create",
            {"name": "E2E", "email": "e2e@example.com",
             "metadata": _tag()},
            specs=specs, clients=clients)
        assert cust["status"] == "executed"
        cus_id = cust["produced"]["customer_id"]

        # NOTE: only scalar fields are changed. Stripe merges metadata maps
        # on update (new keys persist), so a metadata-adding update is not
        # exactly restorable -- documented in the Stripe study (studies/).
        upd = executor.execute(
            conn, run_id, "stripe", "customers.update",
            {"customer": cus_id, "name": "E2E Renamed"},
            specs=specs, clients=clients, declared_deps=[cust["call_id"]])
        assert upd["status"] == "executed"

        prod = executor.execute(
            conn, run_id, "stripe", "products.create",
            {"name": "E2E prod", "metadata": _tag()},
            specs=specs, clients=clients)
        coupon = executor.execute(
            conn, run_id, "stripe", "coupons.create",
            {"percent_off": 10, "duration": "once", "metadata": _tag()},
            specs=specs, clients=clients)
        pi = executor.execute(
            conn, run_id, "stripe", "payment_intents.create",
            {"amount": 200, "currency": "usd", "metadata": _tag()},
            specs=specs, clients=clients)
        assert pi["response"]["status"] == "requires_payment_method"

        # Independent legitimate action: survives.
        indep = executor.execute(
            conn, run_id, "stripe", "customers.create",
            {"name": "Bystander", "metadata": _tag()},
            specs=specs, clients=clients)
        indep_id = indep["produced"]["customer_id"]

        # Fault: confirming without a payment method fails; no money moves.
        fault = executor.execute(
            conn, run_id, "stripe", "payment_intents.confirm",
            {"intent": pi["produced"]["payment_intent_id"]},
            specs=specs, clients=clients,
            declared_deps=[pi["call_id"]])
        assert fault["status"] == "failed"

        out = rollback_exec.start(
            conn, run_id,
            [cust["call_id"], prod["call_id"], coupon["call_id"],
             pi["call_id"]],
            clients=clients, specs=specs)
        assert out["status"] == "completed", out
        assert set(out["outcomes"]) == {
            cust["call_id"], upd["call_id"], prod["call_id"],
            coupon["call_id"], pi["call_id"]}
        assert out["outcomes"][upd["call_id"]] == "restored_exact"
        assert out["outcomes"][pi["call_id"]] == "restored_equivalent"

        stripe = clients["stripe"]
        # Verify by re-reading (independent of the rollback verifier).
        code, gone_cust = stripe.request(
            "GET", "/v1/customers/{customer}", {"customer": cus_id})
        assert code == 200 and gone_cust["deleted"] is True
        for _id in (f"/v1/products/{prod['produced']['product_id']}",
                    f"/v1/coupons/{coupon['produced']['coupon_id']}"):
            code, gone = stripe.request("GET", _id, {})
            assert code == 404, (code, gone)
            assert "error" in gone
        code, canceled = stripe.request(
            "GET", "/v1/payment_intents/{intent}",
            {"intent": pi["produced"]["payment_intent_id"]})
        assert code == 200 and canceled["status"] == "canceled"
        code, live = stripe.request("GET", "/v1/customers/{customer}",
                                    {"customer": indep_id})
        assert code == 200 and live.get("deleted") is not True

        # Cleanup: everything this test created (the PI is already
        # canceled by the rollback under test).
        stripe.request("DELETE", "/v1/customers/{customer}",
                       {"customer": indep_id})
    finally:
        conn.close()
