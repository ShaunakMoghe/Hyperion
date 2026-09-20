"""H-043/H-044: gateway end-to-end via the official SDK client (no mocks).

Client -> gateway subprocess -> demo upstream subprocess; CRM over HTTP;
Postgres real. Rollback afterwards runs through the real CLI subprocess.
"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from hyperion.ledger import store

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]


def _child_env(extra: dict) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(REPO_ROOT / "src"), env.get("PYTHONPATH", "")])
    env.update(extra)
    return env


@pytest.mark.asyncio
async def test_gateway_full_path(env, crm_base_url):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    run_id = store.create_run(env["conn"], client="mcp-test")
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "hyperion.mcp_gateway.proxy"],
        env=_child_env({"HYPERION_RUN_ID": run_id,
                        "CRM_BASE_URL": crm_base_url}),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            # Bounded: a wedged gateway must fail loudly, never hang the suite.
            async with asyncio.timeout(120):
                await session.initialize()

                # tools/list passes through untouched.
                tools = await session.list_tools()
                names = sorted(t.name for t in tools.tools)
                assert names == ["crm_add_note", "crm_create_deal",
                                 "crm_create_lead", "crm_delete_lead",
                                 "crm_get_lead", "crm_send_email",
                                 "crm_update_lead"], names

                # Mapped call is intercepted: ledger row, real CRM object.
                created = await session.call_tool("crm_create_lead",
                                                  {"name": "GW"})
                text = created.content[0].text
                payload = json.loads(text)
                lead_id = payload["response"]["id"]
                assert payload["response"]["name"] == "GW"
                row = store.get_call(env["conn"], payload["call_id"])
                assert row["status"] == "executed"
                assert row["operation"] == "leads.create"

                # Irreversible call is held, never sent.
                held = await session.call_tool(
                    "crm_send_email",
                    {"to": "gw-vp@example.com", "subject": "S", "body": "B"})
                assert "PENDING_APPROVAL" in held.content[0].text

                # Unmapped tool is denied (fail closed).
                with pytest.raises(Exception, match="[Dd]enied"):
                    await session.call_tool("nope_tool", {})

    # Roll back the gateway-created lead through the real CLI.
    cli = subprocess.run(
        [sys.executable, "-m", "hyperion.cli", "rollback", "run",
         "--run", run_id, "--target", payload["call_id"]],
        env=_child_env({"CRM_BASE_URL": crm_base_url}),
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert cli.returncode == 0, cli.stderr[-2000:]
    assert json.loads(cli.stdout)["status"] == "completed"
    code, _ = env["clients"]["crm"].request(
        "GET", "/leads/{lead_id}", {"lead_id": lead_id})
    assert code == 410

    # Held email never delivered.
    snap = env["clients"]["crm"].request("GET", "/snapshot", {})[1]
    assert [e for e in snap["emails_outbox"]
            if e["to_addr"] == "gw-vp@example.com"] == []
