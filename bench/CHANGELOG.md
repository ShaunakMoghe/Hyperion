# Benchmark changelog

The 40 bench-v1 scenarios are frozen at the `bench-v1` tag. After the
tag, every bench change is recorded here with its reason.

## Post-tag fixes

- 2026-09-20: study context fix. Candidate reads/inverses now come from
  any resource sharing a literal path segment with the target, not the
  target's resource only (`bench/synth_study.py`). Reason: same-resource
  grouping hid DELETE /notes/{id} from the notes.add synthesis task
  (different resource prefix), leaving the model no delete signal;
  baseline `synth-20260920-175555` graded 0/9 partly on that artifact.
  Stripe holdout inputs are byte-unchanged (proven by
  `tests/unit/test_bench_grouping.py` plus prompt-hash cache hits on
  rerun). Superseding run: `synth-20260920-175835` (1/9).
- 2026-09-20: prompt v2 (`PROMPT_VERSION` v1 -> v2 in
  `src/hyperion/synth/proposer.py`). The prompt is not a frozen input --
  it is the experiment's independent variable. V1 error analysis showed
  7/9 failures from guessed tombstone shapes (`expect: {deleted: true}`
  on APIs that 404 after delete), so v2 pins the spec_version/id/against
  shapes and restricts `expect` to API-stated terminal values. Run:
  `synth-20260920-180240` (8/9).
