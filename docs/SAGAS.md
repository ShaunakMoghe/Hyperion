# Cross-system sagas

A saga is an ordered list of tool calls that may span systems, run with
all-or-nothing semantics: the first failed or denied step aborts the
saga and compensates every completed step in reverse dependency order.
Held steps pause for a human unless the run auto-approves.

## Statuses

- `completed` — every step executed. Nothing was compensated.
- `compensated` — aborted, and every completed step came back
  (`restored_exact`, `restored_equivalent`, `compensated`, or the
  trivial `skipped_read`).
- `partial` — aborted, compensation ran, but something is left behind:
  an irreversible effect or a conflict.
- `failed` — aborted and compensation itself could not run, including
  any per-step error outcome (an errored step fails the rollback,
  which fails the saga).
- `awaiting_approval` — paused on a held step. Prior steps stand;
  nothing is compensated, because pausing is not aborting.

Compensation is the ordinary rollback engine over the completed steps,
so saga verdicts reuse the bench rollback vocabulary and are directly
comparable. Like the bench runner, compensation forces only when an
irreversible is in scope — otherwise the plan would refuse to start
instead of reporting what survived.

## The scenarios

`bench/scenarios/sagas.yaml`, frozen at the `sagas-v1` tag. Steps name
their system explicitly (unlike bench-v1's one system per scenario);
`$ref`s resolve across steps from produced values.

| Saga | Shape | Expectation |
|------|-------|-------------|
| sag-01 | CRM lead → Stripe customer → CRM deal → Stripe payment intent → CRM note | completes, rolls back clean |
| sag-02 | Lead → customer → payment intent with a bad currency | aborts, customer and lead unwind |
| sag-03 | Lead → product → coupon denied by saga policy | aborts, product and lead unwind |
| sag-04 | Lead → big-ticket deal (held, auto-approved) → customer → note | completes, rolls back clean |
| sag-05 | Sent email (auto-approved) → lead → bad payment intent | aborts, email survives: partial |
| sag-06 | CRM-only chain, no Stripe | completes offline, rolls back clean |

Cross-system lineage falls out of the value-based provenance: the
customer shares the lead's email, the payment intent names the
customer, so the rollback planner sees one dependency graph across
both systems with no saga-specific edge code.

## Results

Recorded at the `sagas-v1` tag (`bench/baselines/sagas-20260926-010951.json`):
6/6 sagas pass with zero unexpected residue (sag-05's surviving email
is the expected, asserted outcome — `partial`, not damage).

| Saga | Saga status | Rollback outcomes |
|------|-------------|-------------------|
| sag-01 | completed | mix of exact and equivalent restores, all 5 steps |
| sag-02 | compensated | customer + lead restored, zero residue |
| sag-03 | compensated | product + lead restored, zero residue |
| sag-04 | completed | all 4 steps restored, zero residue |
| sag-05 | partial | lead restored, sent email correctly reported as surviving |
| sag-06 | completed | all 4 steps restored, zero residue |

No per-step rollback overrides were needed: every outcome matched the
default derived from its spec's effect class and fidelity. In other
words, the saga verdicts fell out of the existing rollback vocabulary
with no special cases — which is the point.

## Limitations

- An abort on the very first step compensates nothing and reports
  `compensated` vacuously. No shipped saga does this; it is the
  degenerate case, documented so it doesn't surprise.
- A failed-but-effectful forward (the call returned 2xx, then
  verification failed) is never compensated — neither the saga nor the
  planner touches non-executed calls. Shipped saga failures are
  no-effect 4xx responses, so this is a known gap, not a live one.
- The runner has no per-saga crash guard: a scenario bug (bad `$ref`,
  unknown op) aborts the whole run instead of recording a failure.
  The freeze validator exists to catch those before they run.
- The baseline artifact records compensation force as the string
  `"compensation"` rather than the bool used, and doesn't carry
  produced ids for the CRM side — the verdicts are auditable, the
  inputs to re-verify them by hand are thinner than bench-v1's.
- Approval-denied sagas (`approvals: deny`, pausing mid-run) aren't
  assertable yet; all shipped sagas auto-approve.
