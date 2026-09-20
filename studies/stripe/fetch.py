"""Fetch the pinned Stripe OpenAPI spec (H-031).

Reads studies/stripe/SPEC_VERSION (commit + sha256), downloads the file
from the stripe/openapi GitHub repo at that commit, verifies the hash, and
writes studies/stripe/openapi.json (gitignored: ~7MB, reproducible).
Usage: `uv run poe stripe-spec` (or python studies/stripe/fetch.py).
"""

import hashlib
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW = "https://raw.githubusercontent.com/stripe/openapi/{commit}/openapi/spec3.json"


def read_version() -> dict:
    fields = {}
    for line in (HERE / "SPEC_VERSION").read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            fields[key.strip()] = value.strip()
    if "commit" not in fields or "sha256" not in fields:
        raise ValueError("SPEC_VERSION must define commit= and sha256=")
    return fields


def main() -> int:
    version = read_version()
    url = RAW.format(commit=version["commit"])
    request = urllib.request.Request(url, headers={"User-Agent": "hyperion"})
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != version["sha256"]:
        print(f"hash mismatch: got {digest}, want {version['sha256']}",
              file=sys.stderr)
        return 1
    (HERE / "openapi.json").write_bytes(data)
    print(f"wrote openapi.json ({len(data)} bytes, {version['commit'][:12]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
