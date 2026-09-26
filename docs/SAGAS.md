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
  an irreversible effect, a conflict, or an error.
- `failed` — aborted and compensation itself could not run.
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

Pending the recorded baseline (`bench/baselines/sagas-*.json`, needs
the `sagas-v1` tag).
