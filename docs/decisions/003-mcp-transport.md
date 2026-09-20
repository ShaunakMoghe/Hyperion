# 003: MCP transport and SDK use

Date: 2026-09-19
Status: accepted

## Context

H-040 requires reading the current MCP spec and Python SDK docs before
building the stdio proxy (H-041). The ecosystem moves fast (working rule 7).

## Findings (verified 2026-09-19 against installed packages and the spec)

- stdio transport is newline-delimited JSON-RPC, no Content-Length framing
  (https://modelcontextprotocol.io/specification/2025-03-26/basic/transports).
- PyPI `mcp` is at 2.2.0 in this project. In v2, `FastMCP` was renamed to
  `MCPServer` (`from mcp.server.mcpserver import MCPServer`); importing
  `mcp.server.fastmcp` raises with a migration pointer. The client API is
  unchanged: `ClientSession` / `StdioServerParameters` / `stdio_client`,
  with `session.list_tools()` and `session.call_tool()`.

## Decision

- Pin `mcp>=2.2` and write all new code against the v2 API.
- The gateway proxy relays raw newline-delimited JSON-RPC frames between
  the downstream client and the upstream server subprocess. Rationale: the
  proxy must be byte-transparent for every method it does not intercept
  (H-041 accept), and a frame relay has no SDK coupling to drift. Only
  `tools/call` requests with a mapped tool are answered locally; everything
  else (including `tools/list`, notifications, batches) passes through.
- The demo CRM server (H-042) and the integration test client (H-044) use
  the official SDK v2 API.

## Consequences

- If the SDK changes framing again, only the demo/test code is affected;
  the proxy speaks the stable wire format.
