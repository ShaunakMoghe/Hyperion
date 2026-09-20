"""Safety blocklist for inverse synthesis (H-062, shared with H-060).

Single source of truth for resource prefixes that proposals must never
touch: account-level, key management, and live-money rails. The inventory
builder (studies/stripe/inventory.py) imports this module.
"""

EXCLUDED_PREFIXES = {
    "accounts": "account-level operations are out of scope",
    "account_links": "account-level operations are out of scope",
    "capabilities": "account-level operations are out of scope",
    "persons": "account PII management is out of scope",
    "api_keys": "key management is never proposed",
    "webhook_endpoints": "account-level delivery config is out of scope",
    "balance": "treasury view, out of study scope",
    "payouts": "live-money rail out of study scope",
    "transfers": "live-money rail out of study scope",
    "topups": "live-money rail out of study scope",
    "issuing": "separate product surface, out of study scope",
    "treasury": "separate product surface, out of study scope",
    "terminal": "hardware-dependent surface, out of study scope",
    "climate": "separate product surface, out of study scope",
    "tax": "separate product surface, out of study scope",
    "sigma": "separate product surface, out of study scope",
    "reporting": "separate product surface, out of study scope",
    "charges": "legacy endpoint; the study uses PaymentIntents",
}


def resource_of(path: str) -> str:
    parts = path.strip("/").split("/")
    return parts[1] if len(parts) > 1 else "(root)"


def block_reason(path: str) -> str | None:
    """Reason the path is blocked, or None when allowed."""
    return EXCLUDED_PREFIXES.get(resource_of(path))
