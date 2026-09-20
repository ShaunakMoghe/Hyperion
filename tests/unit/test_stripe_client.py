"""H-030: key refusal (no network) and redaction (pure)."""

import pytest

from hyperion.systems import stripe_client


@pytest.mark.parametrize("key", [
    "sk_live_abc", "rk_live_abc", "pk_test_abc", "", "notakey", None, 123,
])
def test_non_test_keys_raise_before_any_network(key):
    with pytest.raises(ValueError):
        stripe_client.StripeClient(key)
    with pytest.raises(ValueError):
        stripe_client.check_test_key(key)


@pytest.mark.parametrize("key", ["sk_test_abc", "rk_test_abc"])
def test_test_keys_accepted_without_network(key):
    stripe_client.check_test_key(key)  # must not raise, must not call out


def test_redact_strips_secrets_deeply():
    body = {"id": "pi_1", "client_secret": "s3cr3t",
            "nested": {"secret": "x", "amount": 5},
            "list": [{"api_key": "k"}]}
    out = stripe_client.redact(body)
    assert out == {"id": "pi_1", "client_secret": "[REDACTED]",
                   "nested": {"secret": "[REDACTED]", "amount": 5},
                   "list": [{"api_key": "[REDACTED]"}]}
    assert body["client_secret"] == "s3cr3t"  # input untouched
