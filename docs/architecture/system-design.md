# System Design — ClinicDesk AI v1

## 1. Shape

A **modular monolith** (ADR-001): one Python package `clinicdesk` with three entrypoints sharing the same domain code.

```
           WhatsApp Cloud API      Exotel        Razorpay
                  │ webhooks          │              │
                  ▼                   ▼              ▼
   ┌──────────── Nginx (TLS 1.2+, rate limits, /ws upgrade) ────────────┐
   │                                                                     │
   │  api  (FastAPI, uvicorn)        web (static React build)            │
   │   • REST /api/v1/*              • dashboard, TV display, QR page    │
   │   • /webhooks/* persist-then-ack                                    │
   │   • /ws  queue + inbox events                                       │
   │                                                                     │
   │  worker (ARQ)                                                       │
   │   • process_inbound_event (assistant pipeline)                      │
   │   • outbox dispatcher (WhatsApp/SMS sends, retries)                 │
   │   • scheduler tick (every minute: due scheduled_jobs, SKIP LOCKED)  │
   │   • sweeps: no-show at session end, recall lapse, retention         │
   └───────────────┬────────────────────────────┬────────────────────────┘
                   ▼                            ▼
            PostgreSQL 16+ (RLS)          Redis (ARQ queue, pub/sub, rate limits)
```

**Source of truth is PostgreSQL.** Redis is a transport/cache; losing Redis loses no booking, message or job (NFR-4, NFR-5): inbound events, outbound messages and scheduled jobs are rows; Redis only carries "wake up" signals.

## 2. Module boundaries

`apps/api/src/clinicdesk/modules/<module>/` each with `models.py` (SQLAlchemy), `schemas.py` (Pydantic), `service.py` (business logic, transaction owner), `router.py` (HTTP only), optional `policy.py` (pure rules, no I/O).

Dependency rules (enforced in review, see `.claude/skills/system-architecture`):
1. `router → service → (models, policy, other modules' service interfaces)`. Routers never touch the DB session directly except to pass it on.
2. `policy.py` files are pure functions: no DB, no clock reads (time passed in). All BR-* rules live here so they are unit-testable.
3. `core/` (config, db, security, tenancy context, errors, logging) depends on no module.
4. `assistant` may only act through the **tool layer** (`assistant/tools.py`) which calls module services. It never imports models.
5. External providers (WhatsApp, Exotel, LLM, SMS, Razorpay) are adapters behind protocols in `integrations/`; business code depends on the protocol.
6. Cross-module side effects (send reminder after booking, attribute revenue on arrival) happen via the same DB transaction calling the other service, or via `scheduled_jobs`/outbox rows written in that transaction. No in-memory event bus.

## 3. Critical flows

### 3.1 Inbound WhatsApp message (NFR-1, NFR-4)
```mermaid
sequenceDiagram
  participant M as Meta
  participant A as api /webhooks/whatsapp
  participant DB as Postgres
  participant Q as Redis/ARQ
  participant W as worker
  M->>A: POST (X-Hub-Signature-256)
  A->>A: verify HMAC (reject 401)
  A->>DB: INSERT inbound_events ON CONFLICT (provider, external_id) DO NOTHING
  A->>Q: enqueue process_inbound_event(id) (job_id = event id → dedup)
  A-->>M: 200 (always fast; never after LLM)
  W->>DB: lock event FOR UPDATE SKIP LOCKED, status=processing
  W->>W: tenant (phone_number_id) → patient → consent gate → safety → NLU → state machine → tool
  W->>DB: one txn: booking/state change + audit + outbox rows + event processed
  W->>Q: enqueue dispatch_outbox
```
A periodic sweeper re-enqueues `inbound_events` stuck in `received/processing` > 2 min (worker crash).

### 3.2 Booking (BR-1..4, BR-13)
`booking.service.book()` in one transaction:
1. `policy.validate_booking_window` (horizon BR-2, slot inside an active session, not on holiday/leave, slot aligned).
2. `pg_advisory_xact_lock(hash(clinic, doctor, phone))` → count upcoming for phone+doctor (BR-4).
3. `INSERT appointment` — partial unique index `(doctor_id, slot_start) WHERE status IN active` guarantees BR-1. `IntegrityError` → `SlotTaken` → caller offers next slots (AC-2).
4. audit row + reminder jobs (24 h, 2 h; quiet-hour adjusted) in the same transaction.

### 3.3 Queue (BR-5, BR-6, NFR-2)
State lives in `queue_entries` per doctor session-day. Ordering is a pure function `queue.ordering.next_entry/project_order(entries, now, avg_consult)` (ADR-005). After each mutation commit, the service publishes `queue:{clinic}:{doctor}:{date}` on Redis; the WS hub fans out to dashboards/TV. Patient WhatsApp "N ahead" alerts are computed after each `call_next`.

### 3.4 Scheduled work (NFR-5)
`scheduled_jobs(kind, run_at, dedup_key UNIQUE, status, attempts)`. Worker cron every 60 s claims `run_at <= now()` rows with `FOR UPDATE SKIP LOCKED`, executes idempotently, marks done. Each job re-checks preconditions at execution (appointment still active, patient not opted out, quiet hours, BR-8 rate limit) — rules are evaluated at **send time**, not only schedule time.

### 3.5 Outbound messages (BR-7, BR-9)
Any send = `outbox_messages` row with `idempotency_key UNIQUE`. Dispatcher decides template vs free-form from the conversation's last inbound timestamp (24 h window), applies quiet hours for non-transactional categories, sends via adapter, retries transient errors with exponential backoff (max 6), records provider message id; delivery-status webhooks update it.

## 4. Time
All timestamps stored as `timestamptz` (UTC). Clinic-local logic (sessions, quiet hours, "today") uses the clinic's `timezone` (default `Asia/Kolkata`). Policies take `now` as a parameter.

## 5. Scale estimate (NFR-6)
20k messages/day ≈ 0.25 msg/s average, peaks maybe 5–10/s at 10:00. A single 2-vCPU EC2 with 2 api + 2 worker processes and Postgres handles this with large headroom; the bottleneck is LLM latency, not compute. No microservices, no Kubernetes for v1.

## 6. Engineering assessment (Phase 0, 20 Nov 2026)

* Repository was empty; the FRD (`docs/source/FRD.docx`) is the only input.
* Dev machine: Windows 10, Python 3.14, Node 24, Git 2.55, Docker Desktop (daemon was stopped; started for this project), RTK 0.48.0 (rtk-ai) with Claude hook. A local PostgreSQL 18 service exists but is not used — the project runs its own Postgres/Redis in Docker on ports 5433/6380 to avoid touching it.
* Biggest technical risks: (1) WhatsApp Business onboarding / template approval lead time, (2) assistant quality in mixed Gujarati/Hinglish within 5 s, (3) staff discipline in marking arrivals (drives BR-11 revenue), (4) DPDP obligations needing legal review.

## 7. Open product decisions (owner: product) — conservative defaults in use

| # | Question (FRD §12 + found in analysis) | Default assumed until decided |
|---|---|---|
| Q1 | Own WhatsApp number per clinic vs shared pilot number | Support both. Shared number resolves clinic by a clinic code in the wa.me deep-link / QR text (`#SHAH`); unknown → ask patient to pick clinic. |
| Q2 | Pricing model | Plans table is generic (fee + limits); no revenue share logic in v1. |
| Q3 | First specialty | Both dental and physio templates ship. |
| Q4 | SMS fallback in MVP? | P1; adapter interface + job only, provider not wired. |
| Q5 | BR-12 says "doctor's fee", FR-1.1 says clinic fees | Fee per doctor, defaulting from clinic default fee; fee is snapshotted at attribution. |
| Q6 | Attribution window: how long after a missed call/recall does a booking still count? | 7 days from the trigger message; booking must carry the trigger reference. |
| Q7 | Missed-call message during 21:00–08:00 | Treated as transactional (patient-initiated) → sent immediately; clinic setting can defer. Needs product confirmation. |
| Q8 | BR-6 "fill gaps" exact semantics | ADR-005 algorithm. Validate with pilot clinics. |
| Q9 | No-show cut-off | At session end (FR-5.2) + configurable grace (default 0 min). |
| Q10 | DP-3 "legal timeline" and DP-8 72 h | Configurable SLA; values require legal confirmation against DPDP Rules 2025 before claiming compliance. |
| Q11 | Minors / family members (FR-2.8) — DPDP verifiable parental consent | Booking for a minor is allowed only by the number holder who consents as guardian; flagged for legal review. |
| Q12 | Emergency keyword list (gu/hi/en) | Initial list in code reviewed by a clinician before pilot. |
| Q13 | Does BR-3 (1 h cut-off) bind staff too? | Yes by default; clinic setting `staff_can_override_cutoff` allows audited override. |
| Q14 | BR-5 "token limit": walk-ins only, or walk-ins + arrived bookings? | Walk-ins only (bookings are already capped by slots). |
| Q15 | Does "Next" auto-complete the patient currently with the doctor? | Yes; an explicit "complete current" exists for the last patient. |
| Q16 | Booking request that mentions a symptom ("appointment for tooth pain") | Continue the booking without commenting on the symptom; pure medical questions go to staff. |
| Q17 | Are reminders/recalls opt-in or opt-out? | Opt-in: sent only after an explicit "Yes" (DP-2); STOP revokes. Needs legal confirmation. |
| Q18 | No-show at an evening session end (after 21:00) | Rebook offer deferred to 08:00 next day by quiet hours (BR-7 wins over "same day"). |
| Q20 | Recall when the patient books some other visit with the same doctor | Recall closed as `already_booked` (they are coming anyway); no recall message sent. |
| Q21 | Reminders for staff-booked patients | Only after the desk records consent (`POST /patients/{id}/consents`) or the patient says Yes on WhatsApp (DP-2, Q17). |
| Q22 | Recall send time | 10:00 clinic time on the due date (AC-7 needs ≥ 08:00); configurable later. |
| Q19 | Emergency lexicon for physio | "stroke", "paralysis", "accident" treated as medical (staff), not emergency, to avoid blocking rehab bookings. Clinician review. |
