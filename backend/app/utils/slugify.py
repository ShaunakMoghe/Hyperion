import re
from typing import Optional

SLUG_REGEX = re.compile(r"[^a-z0-9-]+")


def slugify(value: str, fallback: Optional[str] = None) -> str:
    """Generate a URL-friendly slug."""

    value = value.strip().lower()
    value = re.sub(r"\s+", "-", value)
    value = SLUG_REGEX.sub("", value)
    value = re.sub(r"-{2,}", "-", value)
    value = value.strip("-")
    if not value and fallback:
        return slugify(fallback)
    return value or "org"
