# 002: Postgres access and mini-CRM placement

Date: 2026-09-19
Status: accepted

## Context

H-010 needs a ledger store; H-013 needs a mini-CRM with its own schema.
The stack allows psycopg 3 or SQLAlchemy 2 + Alembic.

## Decision

- Use `psycopg[binary]` with hand-written versioned SQL migrations
  (`src/hyperion/ledger/migrations/N_name.up.sql` / `.down.sql`) and a
  small runner. Rationale: the ledger writes are a handful of explicit
  INSERT/UPDATE statements; an ORM would add indirection without benefit
  at this stage. Revisit if query complexity grows.
- UUIDs are generated in Python (`uuid4`), not in SQL, so no extension
  is required.
- The mini-CRM lives in the same Postgres server/database under the SQL
  schema namespace `crm` (tables `crm.leads`, `crm.deals`, `crm.notes`,
  `crm.emails_outbox`). This keeps `docker-compose.yml` to a single
  service while giving the CRM an isolated namespace with its own
  migration (`targets/crm/migrations/*.sql`).

## Consequences

- Migration discipline is manual: every schema change ships an up/down
  pair, and H-010's test applies and rolls back cleanly.
- CRM deletes set `deleted_at` (tombstone) rather than hard-deleting, so
  snapshots can declare tombstones explicitly (H-024).
