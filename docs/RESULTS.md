# Results

Numbers from the recorded baselines in `bench/baselines/`. The agent
tasks ran against the `bench-v1` tag; the synthesis rounds are
documented in `bench/CHANGELOG.md`.

## Agent tasks: 40/40, zero residual damage

File: `bench/baselines/20260920-175341.json`

All 40 scenarios executed, rolled back, and measured exactly as
specified: 20 mini-CRM and 20 Stripe, covering single ops, chains,
failures, and approval gates. No scenario left anything behind that
wasn't a declared terminal state (tombstones, deleted/canceled
objects, compensation records).

Rollback outcomes across the 91 executed calls:

| Outcome | Count | Meaning |
|---|---|---|
| restored_equivalent | 42 | back to an equivalent state (tombstoned creates, canceled intents) |
| restored_exact | 24 | byte-identical to the before-image |
| conflict_detected | 9 | post-image stale after our own downstream call; inverse correctly withheld, terminal state verified separately |
| skipped_irreversible | 8 | terminal by design (sent emails, issued refunds, canceled intents) |
| skipped_read | 3 | reads take no effect; nothing to undo |
| compensated | 2 | money moved and returned |
| error | 3 | redundant compensation rejected by Stripe (see taxonomy) |

Rollback runs: 31 completed, 6 correctly did nothing (failed/denied
scenarios), 3 completed-with-error exactly as specified.

## Synthesis (C1): 0/9 → 1/9 → 8/9

Model: `gemini-3.5-flash-lite`, temperature 0. Three hold-out ops ×
three seeds, graded by live execution (propose → validate → run the
op, run the inverse, re-read, compare).

| Run | Prompt | Pass | File |
|---|---|---|---|
| 1 | v1 | 0/9 | `synth-20260920-175555.json` |
| 2 | v1 + context fix | 1/9 | `synth-20260920-175835.json` |
| 3 | v2 | 8/9 | `synth-20260920-180240.json` |

By operation at v2: coupons 3/3, notes 3/3, products 2/3. Total LLM
spend for all three rounds: ~89k tokens, $0.00 (free tier).

What moved the number:

1. **Harness artifact (v1 → 1/9).** The study only showed the model ops
   from the target's own resource, which hid `DELETE /notes/{id}` from
   the notes.add task (different resource prefix). The model had no
   delete signal and answered "irreversible". Fixed by pooling
   candidates across resources that share a path segment; Stripe
   holdout inputs are byte-identical before and after (their reruns
   were prompt-hash cache hits).
2. **Guessed tombstone shapes (1/9 → 8/9).** Seven v1 failures came
   from the model writing `expect: {deleted: true}` for APIs that 404
   after delete — overgeneralized from the one example that does
   return `deleted: true`. Prompt v2 restricts `expect` to API-stated
   terminal values and pins the id/version/enum shapes. The single
   remaining miss is the model writing `deleted: true` anyway on one
   seed despite the instruction.

## Failure taxonomy

Issues the baselines surfaced that are engine limitations, not
scenario bugs:

1. **Redundant compensation errors instead of detecting prior refunds.**
   When the agent already refunded, rollback's re-refund is rejected
   by Stripe and the step reports `error`. The money is back either
   way, but the engine should check for an existing refund before
   re-issuing. (str-08, str-10, str-20)
2. **Stale post-images after downstream transitions report as
   conflicts.** A payment intent's create-step baseline is stale once
   our own confirm/cancel moves it; rollback reports
   `conflict_detected` and withholds the inapplicable cancel. Correct
   and conservative, but indistinguishable in the ledger from genuine
   external drift. (9 Stripe steps)
3. **Model non-compliance under fixed prompts.** One v2 seed ignored
   an explicit "never guess tombstone shapes" instruction. Order
   effects are real even at temperature 0. (products seed 99)

## What isn't claimed

- The 40 tasks cover CRUD-plus-payment flows on two systems. Anything
  beyond that is untested until new systems get specs and freeze
  hashes.
- The synthesis result is 3 hold-out ops on one small model. It shows
  the loop works and responds to prompt changes; it is not a claim
  about synthesis quality in general.
- Reruns cost real (free-tier) LLM budget and touch live Stripe test
  mode; see `docs/LIMITATIONS.md`.
