"""Stripe test-mode client wrapper (H-030).

- Refuses any key that does not start with sk_test_/rk_test_ BEFORE any
  network call (ValueError, no request sent).
- Idempotency keys on all mutating calls (generated unless provided).
- Retries with backoff via the SDK (max_network_retries).
- Returns captured (status_code, redacted_body); secrets in responses
  (e.g. client_secret) are redacted before anything reaches the ledger.
- The API key is never logged, printed, or stored in the ledger.
"""

from __future__ import annotations

import uuid

import stripe

TEST_PREFIXES = ("sk_test_", "rk_test_")

# Response keys whose values must never reach the ledger or logs.
REDACT_KEYS = {"client_secret", "secret", "api_key"}


def check_test_key(api_key: str) -> None:
    """Raise ValueError unless this is a test-mode key. No network."""
    if not isinstance(api_key, str) or not api_key.startswith(TEST_PREFIXES):
        raise ValueError(
            "refusing non-test Stripe key (need sk_test_ or rk_test_)")

MUTATING = {"POST", "DELETE", "PUT", "PATCH"}


def redact(obj):
    """Deep-copy obj with secret values replaced."""
    if isinstance(obj, dict):
        return {k: ("[REDACTED]" if k in REDACT_KEYS else redact(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


class StripeClient:
    def __init__(self, api_key: str, max_retries: int = 3) -> None:
        check_test_key(api_key)
        self._max_retries = max_retries
        self._client = stripe.StripeClient(
            api_key, max_network_retries=max_retries)

    def request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[int, dict | None]:
        """Returns (status_code, redacted_body_or_None).

        Raises stripe errors for transport/API failures (callers record
        them as failed); never raises for the key (checked at init).
        """
        method = method.upper()
        options: dict = {"max_network_retries": self._max_retries}
        if method in MUTATING:
            options["idempotency_key"] = idempotency_key or str(uuid.uuid4())
        call_params = dict(params or {})
        response = self._client.raw_request(
            method.lower(), path, **call_params, **options)
        code = getattr(response, "code", 0) or 0
        data = getattr(response, "data", None)
        body = redact(dict(data)) if isinstance(data, dict) else None
        return int(code), body
