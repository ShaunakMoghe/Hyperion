"""HTTP transport for systems under test (H-020).

Path templates (`/leads/{lead_id}`) are filled from call args; remaining
args become the JSON body for mutating methods. Uses httpx so tests can
substitute an in-process ASGI transport (real app + real DB, not a mock).
"""

from __future__ import annotations

import re
from typing import Any

import httpx

_PATH_PARAM = re.compile(r"\{([^}]+)\}")


def fill_path(template: str, args: dict) -> tuple[str, dict]:
    """Fill {params} from args. Returns (path, remaining_args)."""
    names = _PATH_PARAM.findall(template)
    missing = [n for n in names if n not in args]
    if missing:
        raise KeyError(f"missing path params {missing} for {template}")
    path = template
    for n in names:
        path = path.replace("{" + n + "}", str(args[n]))
    rest = {k: v for k, v in args.items() if k not in names}
    return path, rest


class SystemClient:
    def __init__(
        self, base_url: str, transport: httpx.BaseTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url, transport=transport, timeout=timeout
        )

    def close(self) -> None:
        self._client.close()

    def request(
        self, method: str, path_template: str, args: dict
    ) -> tuple[int, Any]:
        """Returns (status_code, parsed_json_or_None). Never raises for
        HTTP error statuses; transport errors propagate as exceptions."""
        path, rest = fill_path(path_template, args)
        m = method.upper()
        if m in ("POST", "PUT", "PATCH"):
            resp = self._client.request(m, path, json=rest)
        else:
            resp = self._client.request(m, path, params=rest or None)
        try:
            body = resp.json()
        except ValueError:
            body = None
        return resp.status_code, body
