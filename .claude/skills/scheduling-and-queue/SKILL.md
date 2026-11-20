---
name: scheduling-and-queue
description: Doctor sessions, slot computation, booking locks and policies, walk-in tokens, merged queue ordering and live updates. Use for scheduling, booking or queue work.
---
# Scheduling and queue
**Purpose** No double bookings, fair queues, correct times.
**When to use** `modules/scheduling`, `modules/booking`, `modules/queue`.
**Required context** ADR-0003, ADR-0005, BR-1..BR-6.

## Engineering rules
- Slots are computed from `doctor_sessions` minus `schedule_exceptions` minus active appointments; never materialised.
- BR-1 relies on the partial unique index; translate `IntegrityError` → `SlotTaken` → offer next slots.
- BR-2 horizon, BR-3 cutoff, BR-4 max upcoming (advisory lock), BR-5 token window/limit live in `policy.py` and read clinic settings.
- Reschedule = new appointment + old marked `rescheduled`, one transaction, both audited (AC-4).
- Leave/holiday flags affected appointments `needs_reschedule` (FR-1.3); never silently cancel.
- Queue order only via `queue/ordering.py` (pure). Publish to Redis after commit; WS clients refetch the snapshot.
- Public queue views show token numbers only — no names or phones.
- All local-time logic in the clinic timezone (default Asia/Kolkata).

## Validation checklist
- [ ] Concurrency test with ≥ 10 parallel bookings on one slot
- [ ] IST midnight / session-boundary cases
- [ ] Table-driven BR-6 ordering tests
