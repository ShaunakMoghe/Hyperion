# Prior art and positioning

How Hyperion relates to the work it builds on. The short version: the
saga pattern is the foundation, Cordon is the closest academic work,
and the rest are adjacent tools and patterns. Anything below marked
"skimmed" needs a proper read before being cited in detail.

## Where Hyperion sits

The classic answer to "undo that" in distributed systems is the saga
pattern (Garcia-Molina & Salem, 1987): pair each step with a
compensating action and run compensations in reverse on failure.
Hyperion applies that idea to agent tool calls on third-party APIs,
with two twists the classics don't have: inverses are written as
verifiable specs (executed and re-read, not just invoked), and the
system measures what *couldn't* be undone as a first-class result
instead of treating rollback as all-or-nothing.

Cordon (semantic transactions for agents: lineage graphs, shadow
state, effect outbox, approvals, rollback benchmark) is the closest
published work. The main differences: Hyperion derives and verifies
inverse specs per operation (hand-written or LLM-synthesized) rather
than tracking shadow state, and its benchmark grades both the
synthesis step and the execution/rollback step against live APIs.

Atomix (transactional tool calls with compensation on abort, plus
fault-injection eval) is the closest runnable system; its public code
is the natural candidate if this project ever needs a head-to-head
baseline.

## Reading list

- **Sagas**, Garcia-Molina & Salem, SIGMOD '87 — compensating
  transactions, the foundation everything here rests on.
- **SagaLLM** (arxiv 2503.11951) — saga-style rollback for LLM
  workflows.
- **Atomix** (arxiv 2602.14849, github.com/mpi-dsg/atomix) —
  transactional tool calls, compensation on abort; public code.
- **Cordon** (arxiv 2606.17573) — semantic transactions for agents;
  closest academic work, has its own rollback benchmark.
- **Agentic Transaction / ACID for agents** (arxiv 2608.13900) —
  skimmed only; read before citing.
- **agent-saga** (PyPI) — runtime-derived compensations with a
  pre-flight gate.
- **evoundo** (PyPI) — pre-state capture with selective rollback and
  dependency conflict detection.
- **revoco** (github.com/rsh1k/revoco) — rollback planning with a
  hand-authored inverse registry and hash-chained ledger.
- **agent-undo** (github.com/lui01212/agent-undo) — operation journal
  plus rollback scripts, aimed at coding agents.
- **Restate rollback pattern** (docs.restate.dev) — the
  durable-execution take on sagas for agents.
