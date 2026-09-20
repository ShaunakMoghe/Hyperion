"""H-032: hand-written Stripe specs validate against the pinned OpenAPI."""

import json
from pathlib import Path

import pytest

from hyperion.specs import loader

SPECS_DIR = Path(__file__).resolve().parents[3] / "specs" / "stripe"
OPENAPI = Path(__file__).resolve().parents[3] / "studies" / "stripe" \
    / "openapi.json"

EXPECTED_IDS = {
    "stripe.customers.create", "stripe.customers.update",
    "stripe.payment_intents.create", "stripe.payment_intents.confirm",
    "stripe.payment_intents.cancel", "stripe.refunds.create",
    "stripe.products.create", "stripe.coupons.create",
}


def _known_operations() -> set[tuple[str, str]] | None:
    if not OPENAPI.is_file():
        return None
    spec = json.loads(OPENAPI.read_text(encoding="utf-8"))
    known = set()
    for path, methods in spec["paths"].items():
        for method in methods:
            known.add((method.upper(), path))
    return known


def test_all_stripe_specs_validate():
    specs = loader.load_dir(SPECS_DIR)
    assert set(specs) == EXPECTED_IDS


def test_spec_operations_exist_in_pinned_openapi():
    known = _known_operations()
    if known is None:
        pytest.skip("pinned openapi.json absent (run poe stripe-spec)")
    specs = loader.load_dir(SPECS_DIR, known)
    assert set(specs) == EXPECTED_IDS


def test_each_spec_links_its_docs():
    for path in sorted(SPECS_DIR.glob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        assert "https://docs.stripe.com" in text, path.name
