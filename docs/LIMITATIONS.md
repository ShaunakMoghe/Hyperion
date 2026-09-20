# Hyperion v2 — Limitations

What doesn't work yet, what the prototype assumes, and what would have
to change. If you're evaluating this project, read this file second
(after the README).

## Synthesis (C1)

- **Model alias volatility.** The proposer defaults to a Gemini flash
  alias; vendors rename or retire aliases, so a pinned model id can stop
  resolving. Mitigation: `HYPERION_LLM_MODEL` env override and the model
  id logged per proposal. Remaining risk: reruns on a different model are
  not strictly comparable.
- **Provider 503s under load.** Free-tier demand spikes return 503 during
  proposer/verifier study runs. The study loop retries with backoff, but a
  long outage stalls C1; there is no offline fallback proposer.
- **Hold-out set is small (3 ops).** Proposer quality is graded on
  `stripe.products.create`, `stripe.coupons.create`, `crm.notes.add` only.
  That's enough to show the loop works, not enough to claim generality;
  the frozen set is pinned at the bench-v1 tag.

## Correctness

- **Provenance is scalar-only.** Values that pass through lists, objects,
  or merged metadata fields are not tracked, so multi-hop chains through
  such shapes lose their links. Shared literal values across objects can
  still suggest false links; distinct metadata nonces per run reduce this
  in Stripe, and the CRM tests pin the boundary. Treat provenance as an
  audit hint, not a proof.
- **Inverse fidelity is declared, not derived.** `equivalent` and
  `compensated` inverses satisfy the spec's verify read but may differ in
  unobserved fields (e.g. Stripe metadata merge semantics mean an update
  inverse restores declared fields, not the full object). Exact-restore
  claims hold only where the verify block covers every mutated field.
- **Irreversible ops are measured, not fixed.** `emails.send` and similar
  `irreversible/none` ops execute and are reported as residual damage;
  Hyperion quantifies them but cannot undo them.

## Targets and environment

- **Stripe track needs live test mode.** C2 and the `stripe` pytest mark
  skip without `STRIPE_TEST_KEY`; there is no Stripe mock, so offline CI
  cannot cover the study. Test-mode objects are real API state — runs
  depend on cleanup paths actually executing.
- **Postgres-only.** The ledger and mini-CRM assume Postgres (docker
  compose provided); SQLite is not supported, so the suite needs a
  database up (`uv run poe up`).
- **Windows-first tooling.** Tasks run through `poe`, not `make`; stdio
  transport uses `sys.executable` discovery. Unix shells work but are not
  the tested path.
- **Gateway maps one upstream.** The MCP proxy fronts a single demo
  server via `tool_map.yaml`; multi-server fan-out and streaming tools are
  out of scope.

## Benchmark

- **40 tasks, one domain each.** bench-v1 covers mini-CRM and Stripe
  payment flows only. Generalization beyond CRUD-plus-payment workflows is
  unclaimed until new systems are added under `specs/` with their own
  freeze hashes.
- **Runs cost money and touch live APIs.** Baselines spend LLM budget
  (tracked per proposal against `HYPERION_LLM_BUDGET_USD`) and hit real
  Stripe test mode, so a full rerun is neither free nor hermetic.
