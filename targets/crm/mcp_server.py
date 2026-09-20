"""Demo MCP server exposing mini-CRM tools (H-042).

A stand-in third-party server: each tool calls the CRM over HTTP. When run
behind the Hyperion gateway, mapped tools/call requests are intercepted and
never reach this process; tools/list passes through byte-identical.
"""

import os

import httpx
from mcp.server.mcpserver import MCPServer

BASE = os.environ.get("CRM_BASE_URL", "http://127.0.0.1:8001")

server = MCPServer("hyperion-crm-demo")


def _post(path: str, payload: dict) -> dict:
    r = httpx.post(f"{BASE}{path}", json=payload, timeout=10.0)
    r.raise_for_status()
    return r.json()


def _get(path: str) -> dict:
    r = httpx.get(f"{BASE}{path}", timeout=10.0)
    r.raise_for_status()
    return r.json()


@server.tool()
def crm_create_lead(name: str, email: str = "", metadata: dict | None = None) -> dict:
    """Create a CRM lead."""
    return _post("/leads", {"name": name, "email": email or None,
                            "metadata": metadata or {}})


@server.tool()
def crm_get_lead(lead_id: str) -> dict:
    """Read a CRM lead."""
    return _get(f"/leads/{lead_id}")


@server.tool()
def crm_update_lead(lead_id: str, name: str = "", email: str = "") -> dict:
    """Update a CRM lead's name/email."""
    body = {}
    if name:
        body["name"] = name
    if email:
        body["email"] = email
    r = httpx.patch(f"{BASE}/leads/{lead_id}", json=body, timeout=10.0)
    r.raise_for_status()
    return r.json()


@server.tool()
def crm_delete_lead(lead_id: str) -> dict:
    """Delete (tombstone) a CRM lead."""
    r = httpx.delete(f"{BASE}/leads/{lead_id}", timeout=10.0)
    r.raise_for_status()
    return r.json()


@server.tool()
def crm_create_deal(lead_id: str, title: str, amount_cents: int = 0) -> dict:
    """Create a deal for a lead."""
    return _post("/deals", {"lead_id": lead_id, "title": title,
                            "amount_cents": amount_cents})


@server.tool()
def crm_add_note(deal_id: str, body: str) -> dict:
    """Add a note to a deal."""
    return _post(f"/deals/{deal_id}/notes", {"body": body})


@server.tool()
def crm_send_email(to: str, subject: str, body: str) -> dict:
    """Send an email (irreversible)."""
    return _post("/emails", {"to": to, "subject": subject, "body": body})


if __name__ == "__main__":
    server.run()
