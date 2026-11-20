# ADR-0004 Durable jobs and outbox in Postgres; Redis only as transport
Status: accepted
**Context** NFR-4 (no lost webhooks) and NFR-5 (±5 min). ARQ deferred jobs live only in Redis.
**Decision** `inbound_events`, `outbox_messages`, `scheduled_jobs` are tables written in the business transaction. ARQ executes; a 60 s cron claims due rows with `FOR UPDATE SKIP LOCKED`. Every handler is idempotent and re-validates preconditions at run time (opt-out, quiet hours, appointment still active).
**Consequences** Redis loss delays work by ≤ 1 tick, loses nothing. Jobs table needs pruning (30-day retention of done rows).
