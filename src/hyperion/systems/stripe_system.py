"""Stripe system adapter: SystemClient-compatible interface (H-030/H-033)."""

from __future__ import annotations

from typing import Any

import stripe

from hyperion.executor.clients import fill_path

from .stripe_client import StripeClient, redact


class StripeSystemClient:
    """Adapts StripeClient to the executor's request(method, path, args)
    interface (structural typing; no httpx involved).

    Unlike httpx, the Stripe SDK raises on error statuses, so API errors
    are mapped to (status_code, redacted_error_body) here. Only genuine
    transport failures propagate, and the executor records those as
    failed (fail closed).
    """

    def __init__(self, api_key: str, max_retries: int = 3) -> None:
        self._stripe = StripeClient(api_key, max_retries)

    def close(self) -> None:
        return None

    def request(
        self, method: str, path_template: str, args: dict
    ) -> tuple[int, Any]:
        path, rest = fill_path(path_template, args)
        try:
            return self._stripe.request(method, path, rest)
        except stripe.StripeError as e:
            code = getattr(e, "http_status", 0) or 0
            detail = getattr(e, "json_body", None)
            if not isinstance(detail, dict):
                detail = {"message": str(e)[:200]}
            return int(code), {"error": redact(detail)}
