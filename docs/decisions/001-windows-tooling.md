# 001: Windows-first tooling for M0

Date: 2026-09-19
Status: accepted (human-directed)

## Context

The owner works on Windows without GNU make. The v2 handoff (H-002) names
`make up && make test`, which is not runnable here.

## Decision

- Task runner is `poethepoet` with tasks in `pyproject.toml`
  (`up`, `down`, `test`, `lint`, `bench`, `stripe-spec`).
  H-002 acceptance is `uv run poe up && uv run poe test` from a clean
  checkout (after copying `.env.example` to `.env`).
- Line endings normalized with `.gitattributes` (`* text=auto eol=lf`).
- `.gitignore` covers `.env*` except `.env.example`.
- All Python code uses `pathlib`; no POSIX-only shell assumptions in tasks.
  Process control uses `Popen.kill()` (portable) instead of `kill -9`
  when H-023 lands.

## Consequences

- Contributors need `uv` rather than `make`; CI installs `uv`.
- Note (2026-09-20): both deferred tasks have since landed —
  `stripe-spec` fetches the pinned Stripe OpenAPI snapshot and `bench`
  runs the bench-v1 agent tasks.
