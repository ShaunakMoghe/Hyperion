-- H-010: effect ledger schema (up).
-- UUIDs are generated in Python; no extension required.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version integer PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS runs (
    id uuid PRIMARY KEY,
    started_at timestamptz NOT NULL DEFAULT now(),
    client text NOT NULL DEFAULT '',
    meta jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS calls (
    id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES runs (id),
    seq integer NOT NULL,
    system text NOT NULL,
    operation text NOT NULL,
    args jsonb NOT NULL DEFAULT '{}'::jsonb,
    effect_class text NOT NULL,
    fidelity_expected text NOT NULL,
    status text NOT NULL,
    before_image jsonb,
    response jsonb,
    post_image jsonb,
    spec_id text,
    spec_hash text,
    idempotency_key text UNIQUE,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    prev_hash text NOT NULL,
    entry_hash text NOT NULL,
    UNIQUE (run_id, seq)
);

CREATE TABLE IF NOT EXISTS edges (
    call_id uuid NOT NULL REFERENCES calls (id),
    depends_on_call_id uuid NOT NULL REFERENCES calls (id),
    kind text NOT NULL,
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (call_id, depends_on_call_id),
    CHECK (call_id <> depends_on_call_id)
);

CREATE TABLE IF NOT EXISTS approvals (
    id uuid PRIMARY KEY,
    call_id uuid NOT NULL REFERENCES calls (id),
    status text NOT NULL,
    decided_by text,
    decided_at timestamptz
);

CREATE TABLE IF NOT EXISTS rollbacks (
    id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES runs (id),
    target_call_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    plan jsonb NOT NULL DEFAULT '{}'::jsonb,
    status text NOT NULL,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz
);

CREATE TABLE IF NOT EXISTS rollback_steps (
    id uuid PRIMARY KEY,
    rollback_id uuid NOT NULL REFERENCES rollbacks (id),
    call_id uuid NOT NULL REFERENCES calls (id),
    status text NOT NULL,
    outcome text,
    fidelity_achieved text,
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    idempotency_key text UNIQUE
);

CREATE TABLE IF NOT EXISTS verification_trials (
    id uuid PRIMARY KEY,
    spec_id text NOT NULL,
    model text NOT NULL DEFAULT '',
    prompt_hash text NOT NULL DEFAULT '',
    trial_no integer NOT NULL,
    outcome text NOT NULL,
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (spec_id, prompt_hash, trial_no)
);
