# Database Design

PostgreSQL 16+ (tested on 16 in Docker). UUIDv4 primary keys (`gen_random_uuid()`), `timestamptz` everywhere, `created_at/updated_at` on every table. Migrations: Alembic, one revision per change, never edited after merge.

## Tenancy
* **Platform tables** (no `clinic_id`, no RLS): `plans`, `users`, `otp_challenges`, `refresh_tokens`, `inbound_events`, `support_access_grants`.
* **Tenant tables**: everything else has `clinic_id NOT NULL` → `clinics.id`, and RLS (ADR-002):
  ```sql
  ALTER TABLE t ENABLE ROW LEVEL SECURITY; ALTER TABLE t FORCE ROW LEVEL SECURITY;
  CREATE POLICY tenant_isolation ON t USING (
     clinic_id = NULLIF(current_setting('app.clinic_id', true), '')::uuid
     OR current_setting('app.bypass_rls', true) = 'on');
  ```
  `app.clinic_id` is set with `set_config(..., true)` (transaction-local) by the request/job session factory. Pool connections therefore never leak tenant context.
* Composite FKs `(clinic_id, id)` on child→parent references inside a tenant (e.g. appointment → doctor) so a row can never point at another clinic's parent.

## Entities (v1)

| Table | Key columns | Notes |
|---|---|---|
| clinics | name, slug (clinic code), specialty, timezone, languages[], address, map_url, default_fee_paise, settings jsonb, plan_id, trial_ends_at, status | `settings`: booking_horizon_days (BR-2), change_cutoff_minutes (BR-3), max_upcoming_per_doctor (BR-4), token_window_minutes (BR-5), alert_ahead (FR-4.3), quiet hours |
| users | phone (E.164, unique), name, is_platform_admin | global identity |
| clinic_memberships | clinic_id, user_id, role {owner, doctor, receptionist}, doctor_id?, status {invited, active, disabled} | unique (clinic_id, user_id) |
| doctors | clinic_id, name, fee_paise, slot_minutes, is_active | |
| doctor_sessions | clinic_id, doctor_id, weekday 0–6, start_time, end_time, max_tokens, effective_from/to | weekly template (FR-1.2) |
| schedule_exceptions | clinic_id, doctor_id NULL (=whole clinic), start_date, end_date, kind {holiday, leave}, reason | FR-1.3 |
| patients | clinic_id, phone, name, age, language, account_holder_id (self FK for family) , opted_out_at | unique (clinic_id, phone, name) |
| consent_events | clinic_id, patient_id, purpose {booking, reminders, recalls}, granted bool, channel, notice_version, at | append-only (DP-2) |
| appointments | clinic_id, doctor_id, patient_id, booked_by_phone, slot_start, slot_end, status {booked, confirmed, arrived, completed, cancelled, rescheduled, no_show}, source {assistant, staff, missed_call, recall, noshow_rebook}, source_ref_id, rescheduled_from_id, needs_reschedule bool, arrived_at, completed_at | **`uq_appt_active_slot` UNIQUE (doctor_id, slot_start) WHERE status IN ('booked','confirmed','arrived','completed')** (BR-1) |
| queue_entries | clinic_id, doctor_id, session_date, session_start, token_no, kind {booked, walk_in}, appointment_id?, patient_id?, status {waiting, called, skipped, completed, cancelled}, issued_at, called_at, completed_at, channel | unique (doctor_id, session_date, session_start, token_no) |
| audit_log | clinic_id NULL, actor_type {user, patient, system, assistant}, actor_id, channel {dashboard, whatsapp, system, api}, action, entity_type, entity_id, before jsonb, after jsonb, request_id, at | append-only; app role has no UPDATE/DELETE grant (BR-13) |
| conversations / messages | clinic_id, patient phone, state jsonb, mode {assistant, staff}, last_inbound_at | 24 h window (BR-9) |
| outbox_messages | clinic_id, to_phone, category {transactional, reminder, recall, promo}, template_name?, body jsonb, idempotency_key UNIQUE, status, attempts, next_attempt_at, provider_message_id | |
| scheduled_jobs | clinic_id, kind, run_at, payload jsonb, dedup_key UNIQUE, status, attempts | NFR-5 |
| inbound_events | provider, external_id, payload, status | UNIQUE (provider, external_id) (dedup) |
| missed_calls | clinic_id, caller_phone, called_at, status {pending, recovered, call_back_needed}, message_outbox_id | FR-3.x |
| recall_rules / recalls / treatment_plans | see recall skill | FR-6.x |
| handover_tickets | clinic_id, conversation_id, reason {medical, emergency, complaint, unclear, dsr, other}, status | FR-8.x |
| recovery_attributions | clinic_id, appointment_id UNIQUE, source, fee_paise, recovered_at | BR-11/12; unique prevents double count |
| dsr_requests | clinic_id, patient_id, kind {access, correction, deletion}, due_at, status | DP-3 |

Money is integer paise. Phones are E.164 strings validated at the edge.

## Indexes (initial)
* appointments: `(clinic_id, doctor_id, slot_start)`, `(clinic_id, patient_id, slot_start)`, partial unique above, `(clinic_id, status, slot_end)` for no-show sweep.
* scheduled_jobs: `(status, run_at)` partial where status='pending'.
* outbox_messages: `(status, next_attempt_at)`.
* patients: `(clinic_id, phone)`, trigram on name added when search needs it (FR-7.2).

## Roles
* `clinicdesk_owner` — owns schema, runs migrations.
* `clinicdesk_app` — runtime; DML only; no UPDATE/DELETE on `audit_log`; subject to RLS (not owner, no BYPASSRLS).
