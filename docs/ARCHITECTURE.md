# Hyperion v2 — Architecture

Hyperion derives, verifies, and executes inverses for agent tool calls,
then measures reversible damage: after an agent acts, every effect is
checked against a spec and rolled back, and whatever is left over is the
measured damage. The evaluation has two tracks. C1 (synthesis) asks
whether an LLM can write correct inverse specs. C2 (Stripe study) asks
whether the whole thing holds up against a real third-party API.

## Components

```
specs/crm/*.yaml, specs/stripe/*.yaml   human inverse specs (ground truth)
src/hyperion/specs/                     schema_v1.json + loader/validator
src/hyperion/ledger/                    Postgres run/event ledger (db, store)
src/hyperion/executor/                  executor, approvals, rollback plan+exec,
                                        provenance, policy
src/hyperion/mcp_gateway/               stdio frame-relay proxy + tool_map.yaml
src/hyperion/systems/                   Stripe test-mode client + system adapter
src/hyperion/synth/                     LLM proposer, safety filter, validator, verifier
targets/crm/                            mini-CRM (FastAPI + Postgres) + MCP demo server
studies/stripe/                         pinned OpenAPI fetch + operation inventory
bench/scenarios/v1.yaml                 task set (frozen at bench-v1 tag)
```

## Specs

One YAML file per operation (`<resource>.<verb>.yaml`). Each spec states
the operation (method + path), an `effect_class`/`fidelity` pair, an
optional `before_image` read, the values it `produces`, its `inverse`, a
`verify` read with field comparison, and `provenance` rules:

- `read/exact` — no effect, `inverse: null`.
- `reversible/exact|equivalent` — inverse restores the same state.
- `compensable/compensated` — inverse undoes the money movement
  (e.g. confirm then refund); the ledger records the compensation.
- `irreversible/none` — e.g. sending an email; rollback skips it and the
  residual is reported as damage.

Terminal states need exact-match comparison: `verify.compare.expect` pins
values such as a canceled payment intent's `status: canceled` instead of
comparing against a moving target. Creates have `before_image: null` and
produce server-generated ids from `$.response`.

## Execution pipeline

1. **Propose (synth).** The proposer sends one LLM prompt per operation:
   its OpenAPI fragment, sibling operations, candidate reads/inverses, and
   few-shot examples from human specs *excluding* the hold-out set
   (`stripe.products.create`, `stripe.coupons.create`, `crm.notes.add`).
   Temperature 0; model id, prompt hash, tokens, and cost are logged and
   proposals cache by (operation, spec version, prompt version, model,
   prompt content hash), so prompt changes never hit stale entries.
   A shared safety blocklist rejects obviously dangerous proposals.
2. **Validate.** Structural validation against `schema_v1.json` plus the
   validator's cross-checks (inverse targets a real op, templates resolve).
3. **Verify.** The verifier executes the op live, runs the inverse, and
   re-reads: pass means the before/after states match per the spec.
4. **Execute + roll back.** The executor runs agent plans through the
   ledger: each call is policy-checked, executed, verified, and appended
   to a rollback plan. Rollback replays inverses in reverse; anything left
   is measured damage.

## Safety gates

- **Policy** (`executor/policy.py`, `docs/POLICY.md`): YAML
  allow/deny/`require_approval` rules with a fail-closed engine — missing
  file, bad rule, or unparsable condition decides DENY. `when` conditions
  use a hand-walked AST subset, never `eval`. The gateway enforces its
  policy file on every intercepted call and stamps the file's sha256 on
  the run; a configured-but-unloadable policy stops the gateway at
  startup instead of denying calls one by one.
- **Approvals**: gated ops return `PENDING_APPROVAL` instead of executing;
  bench scenarios run with `auto` or `deny` presets. Humans list and
  decide holds via `hyperion approvals` / `approve` / `deny`, and
  `hyperion ledger export` emits the per-run audit artifact.
- **Provenance** (`executor/provenance.py`): links produced values (e.g. a
  created id) to later calls that consume them, scalar-only, so shared or
  merged values never create false links.
- **Stripe guardrails**: the client refuses live keys and non-test mode;
  every test run stamps distinct metadata nonces so objects never merge.

## Targets

- **mini-CRM** (`targets/crm/`): FastAPI + Postgres (Postgres-only docker
  compose; raw-SQL migrations via psycopg). Leads/deals CRUD with restore,
  notes, email outbox, plus a canonical `GET /snapshot` used for
  state diffing and bench freeze hashes.
- **Stripe**: real test-mode API through a thin wrapper. The OpenAPI
  snapshot is pinned (`studies/stripe/SPEC_VERSION` + sha256) and the
  operation inventory is generated from it, not hand-written.
- **Gateway** (`mcp_gateway/proxy.py`): a stdio MCP proxy that launches the
  upstream server with the local Python, passes `tools/list` through, and
  routes mapped `tools/call` requests through the spec executor with
  ledgering. The demo server (`targets/crm/mcp_server.py`) plus
  `docs/DEMO.md` show it working from Claude Desktop.

## Evaluation

- **C1 synthesis bench**: proposer output on hold-out ops × seeds, graded
  by the verifier against live execution.
- **Agent tasks** (`bench/scenarios/v1.yaml`): 40 fixed NL tasks (20 CRM,
  20 Stripe) covering single ops, chains, failures, and approval gates,
  each with a concrete call script and an expected rollback outcome
  (clean / compensated / partial / trivial / blocked).
- The set gets frozen under the `bench-v1` tag with dataset hashes
  (CRM schema, Stripe spec pin) before any baseline runs. Post-tag
  scenario changes are logged in `bench/CHANGELOG.md` with reasons.

## Tooling (Windows-first)

`uv run poe up/test/lint`, `poe stripe-spec`; `pytest tests -q`;
`ruff check src tests targets studies`. Line endings LF
(`.gitattributes`), `.env*` ignored except `.env.example`, live keys never
printed or committed.
