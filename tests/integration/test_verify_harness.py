"""H-063: harness reproduces hand-spec outcomes; wrong specs fail (live)."""

import copy
import os

import pytest

from hyperion.ledger import db
from hyperion.specs import loader
from hyperion.systems.stripe_system import StripeSystemClient
from hyperion.synth import verifier

pytestmark = pytest.mark.stripe

EXPECTED = {
    "stripe.customers.create": "verified_equivalent",
    "stripe.customers.update": "verified_exact",
    "stripe.payment_intents.create": "verified_equivalent",
    "stripe.payment_intents.confirm": "verified_compensated",
    "stripe.payment_intents.cancel": "skipped_held",
    "stripe.refunds.create": "skipped_held",
    "stripe.products.create": "verified_exact",
    "stripe.coupons.create": "verified_exact",
}


def _client():
    return StripeSystemClient(os.environ["STRIPE_TEST_KEY"])


def test_hand_specs_reproduce_expected_outcomes():
    from pathlib import Path

    specs = loader.load_dir(
        Path(__file__).resolve().parents[2] / "specs" / "stripe")
    assert set(specs) == set(EXPECTED)
    conn = db.connect()
    try:
        for spec_id, want in sorted(EXPECTED.items()):
            trials = 3 if spec_id == "stripe.customers.update" else 1
            result = verifier.verify_spec(
                _client(), specs[spec_id], conn, model="human", trials=trials)
            assert result["outcome"] == want, (spec_id, result)
    finally:
        conn.close()


def test_deliberately_wrong_spec_fails():
    from pathlib import Path

    specs = loader.load_dir(
        Path(__file__).resolve().parents[2] / "specs" / "stripe")
    wrong = copy.deepcopy(specs["stripe.customers.create"])
    wrong["inverse"]["operation"] = {"method": "DELETE",
                                     "path": "/v1/products/{id}"}
    wrong["inverse"]["params"] = {"id": "$.produced.customer_id"}
    result = verifier.verify_spec(_client(), wrong, None, model="human",
                                  trials=1)
    assert result["outcome"] in ("failed_inverse", "state_mismatch"), result
