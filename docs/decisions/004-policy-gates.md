# 004: Policy gates as a first-class feature

Date: 2026-09-24
Status: accepted

## Context

The policy engine (`executor/policy.py`, H-052) existed but only the
bench runner used it: the gateway never passed a policy, held calls had
no list command, and deny/hold reasons lived only in return values. M9
promotes all of that to a usable governance layer.

## Decision

- The tool map gains a `policy:` key; `HYPERION_POLICY` overrides it
  per run. The gateway reads the file once at startup and passes the
  parsed dict to every `execute()` call (mapped and unmapped tools
  alike), so enforcement can't drift from the stamp.
- A configured-but-unloadable policy stops the gateway at startup
  (exit 2) instead of denying every call one by one.
- The run records its governing policy's sha256 at creation; mid-run
  file edits don't change enforcement, and resuming a stamped run
  under a different policy file is refused.
- Deny/hold reasons are stored on the call row (`decision_reason`,
  migration 002). Like `status`, the field is excluded from the hash
  chain: it is executor state, not ledger evidence. Including it would
  have broken verification of every pre-M9 row.
- `hyperion approvals` lists pending holds; `hyperion ledger export`
  emits the audit artifact (run meta, chain verdict, calls with
  reasons, approvals with deciders), with secret-bearing args redacted.
- Policy stays Hyperion-native YAML. MCP governance extensions were
  still proposals at build time; tracking them would couple the gate
  to a moving spec. Revisit when they stabilize.

## Consequences

- The default tool map ships governed (`gateway/policy.yaml`,
  default-allow). Policy sees unmapped tools too (as system `mcp`),
  so a rule can hold or deny them explicitly; otherwise the map's
  `unknown:` setting applies as before.
- Per-principal scoping is deferred (see `docs/POLICY.md`).
