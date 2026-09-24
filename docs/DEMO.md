# Demo

Two ways to show Hyperion: the dashboard (recommended, visual) and the
raw gateway (for engineers who want the wire). Both run locally.

## Dashboard (90 seconds)

Prerequisites: Docker Desktop running, then Postgres:

```powershell
poe up
```

Three terminals, from the repo root:

```powershell
# 1. API (port 8000; boots its own CRM automatically)
poe dashboard

# 2. web (port 3000)
poe dashboard-web

# 3. one-time seed (fresh demo run each time you run it)
poe dashboard-seed
```

Open http://localhost:3000 in a browser, click the `dashboard-demo`
run. The script:

| Beat | Do | Say |
|------|----|-----|
| 0:00 | Runs list → open the demo run | "Every agent action lands in a Postgres ledger — this is one run, seven calls." |
| 0:15 | Point at the graph: green chain, amber holds, red denial | "Four executed, two held for approval, one denied by policy. The denied delete never touched the CRM." |
| 0:30 | Click the amber email node | "The email is irreversible, so it's held — full args and the reason are right here." |
| 0:40 | Approvals → approve the big deal | "A human approves, the call executes exactly once." |
| 0:55 | Roll back run (the button asks once — it unwinds the whole run) | "And everything reversible unwinds in dependency order — watch the nodes go gray." |
| 1:10 | Export audit JSON | "The whole run — policy hash, chain verdict, every decision — exports as one artifact." |

Tips for the recording: seed a fresh run right before you start (the
"started" timestamp reads as live), and approve — don't deny — the big
deal, so the rollback has five calls to unwind instead of four.

## Gateway + mini-CRM through a real MCP client

Prerequisites: Postgres up (`poe up`), CRM running, then the gateway.

```powershell
poe up
$env:PYTHONPATH = "src"
python targets/crm/app.py          # CRM on http://127.0.0.1:8001
python -m hyperion.mcp_gateway.proxy   # gateway on stdio
```

The gateway launches the upstream demo server
(`targets/crm/mcp_server.py`) itself using `gateway/tool_map.yaml`.
`tools/list` passes through untouched; mapped `tools/call` requests run
through the spec executor and are ledgered; unmapped tools are denied.

### Claude Desktop (verified config format)

Claude Desktop launches stdio servers from `%APPDATA%\Claude\claude_desktop_config.json`
with `mcpServers: { name: { command, args, env } }`. Point it at the gateway:

```json
{
  "mcpServers": {
    "hyperion-crm": {
      "command": "python",
      "args": ["-m", "hyperion.mcp_gateway.proxy"],
      "env": {
        "PYTHONPATH": "C:\\Users\\blazi\\Hyperion\\src",
        "CRM_BASE_URL": "http://127.0.0.1:8001"
      }
    }
  }
}
```

Restart Claude Desktop after editing. Try: "create a lead named Ada",
then "send an email" — the email is held with a `PENDING_APPROVAL`
result instead of being sent. Approve from a terminal:

```powershell
$env:PYTHONPATH = "src"
python -m hyperion.cli approve <call_id> --by you
```

### What to show (90 seconds)

1. List tools (passthrough) — 7 `crm_*` tools.
2. `crm_create_lead` — intercepted, ledgered, real CRM row.
3. `crm_send_email` — held, `PENDING_APPROVAL`, nothing delivered.
4. `hyperion rollback run` — lead tombstoned, verified by re-read.
