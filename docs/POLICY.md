# Policy gates

Every intercepted tool call passes through a policy check before it
runs. The policy is a small YAML file with three possible outcomes per
call: run it, block it, or hold it for a human.

## The file

`gateway/policy.yaml` is the default. It looks like this:

```yaml
default: allow
rules:
  - match: {system: crm, operation: deals.create,
            when: "amount_cents > 100000"}
    effect: require_approval
  - match: {system: crm, operation: emails.send}
    effect: require_approval
```

Rules match on system + operation, first match wins, and anything
matching nothing falls through to `default`. `default: deny` gives you
an allowlist: block everything except what a rule permits.

The `when` clause is a small expression over the call's arguments —
comparisons, `and`/`or`/`not`, nothing else. It is parsed as an AST,
never `eval`'d, and anything it can't parse or evaluate denies the
call. See `executor/policy.py` for the exact subset.

## Where it plugs in

The gateway reads its policy from the tool map:

```yaml
policy: gateway/policy.yaml
```

`HYPERION_POLICY` overrides that per run, which is how you give one
session a stricter policy without touching the shared file. Relative
paths resolve against the repo root.

Two behaviors worth knowing:

- A configured policy that can't be loaded — missing file, bad YAML,
  bad rule shape — stops the gateway at startup with exit 2. Running
  every call into a deny would be technically fail-closed but
  operationally useless, so it refuses to start instead.
- The gateway loads its policy once at startup and enforces that
  parsed copy for the whole process. Editing the file mid-run changes
  nothing until restart, and the sha256 recorded in the run metadata
  always describes exactly what was enforced — the hash and the parse
  come from the same single read.
- Resuming a run (`HYPERION_RUN_ID`) under a different policy file is
  refused at startup: the run keeps the stamp it was created with, and
  mixing enforcement would make the audit export attest the wrong
  policy. Pre-M9 runs have no stamp, so they resume under whatever
  policy is configured.

The executor also accepts a policy per call (`execute(policy_path=...
or policy={...})`), which is what the bench runner uses. Same engine,
same fail-closed semantics — but note a per-call path re-reads the
file each time, so the fixed-at-creation guarantee is a gateway
property, not an executor one.

## The approval loop

A `require_approval` decision — or any call the executor deems
irreversible — holds the call instead of running it. The agent gets
back `PENDING_APPROVAL` plus the ledger call id. Nothing executes until
a human decides:

```
hyperion approvals --run <run-id>   # what's waiting
hyperion approve <call-id> --by <you>
hyperion deny <call-id> --by <you>
```

Approving runs the held call exactly once (a per-call idempotency key
makes double-approves safe); denying flips it to blocked. Both record
who decided and when. Omit `--run` to see everything pending across
all runs.

The pending list shows raw call arguments, including any secrets —
deliberately, since the decider needs the full picture to judge the
call. The audit export is the redacted artifact; the approvals queue
is the working one. Don't pipe `hyperion approvals` into a log.

## Denials

A denied call is still a ledger row: status `blocked`, with the reason
recorded alongside it. The agent's error response includes the call id
as a receipt, so a denial is always traceable to the exact row and
rule that caused it.

## Audit export

`hyperion ledger export --run <run-id>` emits one JSON artifact with
the run metadata (including the policy sha256), the hash-chain
verdict, every call with its decision reason, and every approval with
its decider. Secrets in arguments are redacted with the same `redact()`
the Stripe client uses. Write it to a file with `--out`; the command
exits nonzero if the chain doesn't verify.

## What's deliberately missing

Per-user/per-principal rules aren't here yet. MCP's own identity story
was still churning when this was built (the July 2026 spec moved the
security boundary), so policy is per-tool and per-run only — building
principal scoping against a moving spec would have produced the worst
kind of compatibility: the kind that looks right. The seam is clean
when the spec settles: `decide()` takes the call's identity as one
more match field.
