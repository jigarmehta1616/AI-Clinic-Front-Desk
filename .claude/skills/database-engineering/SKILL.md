---
name: database-engineering
description: PostgreSQL schema, Alembic migrations, indexes, RLS tenant isolation and transaction integrity. Use when changing models, writing migrations or queries.
---
# Database engineering
**Purpose** Keep invariants in the database and tenants isolated.
**When to use** Models, migrations, queries, locking.
**Required context** `docs/architecture/database-design.md`, ADR-0002, ADR-0003, latest file in `apps/api/migrations/versions/`.

## Engineering rules
- Every tenant table: `clinic_id NOT NULL`, RLS enabled + forced with the `tenant_isolation` policy (use the `enable_rls()` helper in migrations).
- Invariants live in the DB: unique / partial unique indexes, CHECK constraints, FKs. App checks are UX, not protection.
- One Alembic revision per change, working `downgrade`, never edit a merged revision, no data-destroying op without ADR + backup.
- Money = integer paise; timestamps = `timestamptz` UTC; phones = E.164.
- Job claiming: `FOR UPDATE SKIP LOCKED`. Count-then-insert rules: `pg_advisory_xact_lock`.
- Avoid N+1 (`selectinload`/joins); add an index together with the query that needs it.
- Runtime role `clinicdesk_app` is not the owner and has no BYPASSRLS; tests connect as it.

## Validation checklist
- [ ] `alembic upgrade head`, `downgrade -1`, `upgrade head` pass on a fresh DB
- [ ] Cross-tenant test covers the new table
- [ ] EXPLAIN checked for new hot queries
