# ADR-0003 Booking concurrency
Status: accepted
**Decision** BR-1: partial unique index on `appointments(doctor_id, slot_start) WHERE status IN ('booked','confirmed','arrived','completed')`; a violating insert raises `SlotTaken`. Correct under any isolation level and across processes; no app-level lock needed. BR-4: `pg_advisory_xact_lock(hashtextextended(clinic|doctor|phone))` serialises the count-then-insert for one phone+doctor. Reschedule = insert new + mark old `rescheduled` in one transaction (old slot freed on commit, FR-2.4).
**Rejected** SERIALIZABLE everywhere (retry storms, harder to reason about); materialised slot rows with `FOR UPDATE` (needs slot generation jobs, holiday regeneration).
