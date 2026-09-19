-- H-013: mini-CRM schema (up). Own namespace `crm` on the shared server.

CREATE SCHEMA IF NOT EXISTS crm;

CREATE TABLE IF NOT EXISTS crm.leads (
    id uuid PRIMARY KEY,
    name text NOT NULL,
    email text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz
);

CREATE TABLE IF NOT EXISTS crm.deals (
    id uuid PRIMARY KEY,
    lead_id uuid NOT NULL REFERENCES crm.leads (id),
    title text NOT NULL,
    amount_cents integer NOT NULL DEFAULT 0 CHECK (amount_cents >= 0),
    stage text NOT NULL DEFAULT 'open',
    created_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz
);

CREATE TABLE IF NOT EXISTS crm.notes (
    id uuid PRIMARY KEY,
    deal_id uuid NOT NULL REFERENCES crm.deals (id),
    body text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Sending is irreversible: the row below IS the delivery.
CREATE TABLE IF NOT EXISTS crm.emails_outbox (
    id uuid PRIMARY KEY,
    to_addr text NOT NULL,
    subject text NOT NULL,
    body text NOT NULL,
    delivered_at timestamptz NOT NULL DEFAULT now()
);
