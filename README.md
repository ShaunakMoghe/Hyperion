# Hyperion

Hyperion derives, verifies, and executes inverses for agent tool calls
against third-party APIs — then measures how much of an agent's
side-effect damage can actually be undone.

The core loop: every tool call runs against a spec describing its
inverse. Afterwards the system rolls everything back and reports what
couldn't be restored. Two tracks evaluate it: C1, where an LLM writes
the inverse specs themselves, and C2, a study against the real Stripe
test-mode API.

## Status

Working system on branch `v2`, benchmarked at the `bench-v1` tag:
40/40 agent tasks with zero residual damage, synthesis 8/9 after one
prompt iteration (see `docs/RESULTS.md`). The earlier prototype is
tagged `v1-prototype` and kept under `legacy/`.

What exists today:

- Append-only Postgres ledger with a hash chain, plus a versioned
  inverse-spec format (`specs/`)
- Mini-CRM target (FastAPI + Postgres) with snapshot/restore support
- Executor with an irreversible-action hold queue, policy engine
  (allow/deny/require approval), and provenance tracking
- Rollback planner (dependents closure) and a persisted, resumable
  rollback state machine
- MCP stdio gateway: frame relay plus `tools/call` interception, with a
  demo CRM server and CLI (`rollback plan/run/resume`, `approve`/`deny`,
  `ledger verify`)
- Stripe test-mode track: pinned OpenAPI fetch, 8 hand-written specs,
  live end-to-end with rollback and cleanup
- LLM synthesis track: spec proposer (Gemini), static validator, and a
  live-execution verifier

Test suite: 149 passed, 1 xfailed (`pytest tests -q`; Stripe/LLM tests
self-skip without keys).

## Quickstart

Windows-first; tasks use `poethepoet` (see
`docs/decisions/001-windows-tooling.md`):

- `uv run poe up` — start Postgres 16
- `uv run poe test` — run the suite
- `uv run poe lint` — ruff check

Copy `.env.example` to `.env` for local runs. Stripe paths only accept
test keys (`sk_test_` / `rk_test_`), and the LLM track needs
`HYPERION_LLM_PROVIDER=gemini`, `HYPERION_LLM_MODEL`, and
`GEMINI_API_KEY`.

For the full picture, start with `docs/ARCHITECTURE.md`. For the
90-second version, see `docs/DEMO.md`.

## Benchmarks

The bench-v1 scenario set (40 tasks: 20 mini-CRM, 20 Stripe, frozen at
the `bench-v1` tag with hashes in `bench/scenarios/v1.freeze.json`)
passes 40/40 with zero residual damage; the synthesis track grades
8/9 hold-out specs by live execution. Raw runs live in
`bench/baselines/`, the writeup (including the failure taxonomy) in
`docs/RESULTS.md`. Nothing is claimed without a number there.

## Prior art

Related work this builds on:

| Work | Link | Relevance |
|---|---|---|
| Sagas (Garcia-Molina & Salem, 1987) | SIGMOD '87 | Compensating transactions: the foundation |
| SagaLLM | https://arxiv.org/abs/2503.11951 | Saga-style rollback for LLM workflows |
| Atomix | https://arxiv.org/abs/2602.14849, https://github.com/mpi-dsg/atomix | Transactional tool calls, compensation on abort, fault-injection eval; public code, candidate baseline |
| Cordon | https://arxiv.org/abs/2606.17573 | Semantic transactions: lineage graph, shadow state, effect outbox, approvals, rollback benchmark. Closest academic work |
| Agentic Transaction (ACID for agents) | https://arxiv.org/abs/2608.13900 | Skimmed only; read before citing details |
| agent-saga | https://pypi.org/project/agent-saga | Runtime-derived compensations, typed semantics, pre-flight gate |
| evoundo | https://pypi.org/project/evoundo | Pre-state capture, selective rollback with dependency conflict detection |
| revoco | https://github.com/rsh1k/revoco | Rollback planning, canary drills, hash-chained ledger; hand-authored inverse registry |
| agent-undo | https://github.com/lui01212/agent-undo | Operation journal + rollback scripts for coding agents |
| Restate rollback pattern | https://docs.restate.dev/ai/patterns/rollback | Durable-execution saga pattern for agents |
