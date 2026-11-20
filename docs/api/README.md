# API (v1)

Live schema: `GET /api/v1/openapi.json` (FastAPI). This page lists contracts that matter for clients.

## Auth
`POST /auth/otp/request {phone}` → 202 · `POST /auth/otp/verify {phone, code}` → access token (+ `cd_refresh` HttpOnly cookie, path `/api/v1/auth`) · `POST /auth/select-clinic {clinic_id}` · `POST /auth/refresh` (cookie) · `POST /auth/logout` · `GET /auth/me`.
Bearer access token on every other route. Tenant comes only from the token.

## Resources (M1)
| Method & path | Permission | Notes |
|---|---|---|
| `POST /clinics` | signed-in user | onboarding; returns clinic + owner tokens |
| `GET/PATCH /clinic` | clinic.read / clinic.manage | settings = BR parameters |
| `POST/GET /clinic/staff` | staff.manage | invite by phone + role |
| `POST/GET /doctors`, `PATCH /doctors/{id}` | doctor.manage / schedule.read | |
| `PUT /doctors/{id}/sessions` | doctor.manage | replaces weekly template |
| `GET /doctors/{id}/slots?from&to&limit` | schedule.read | free slots within horizon |
| `POST/GET /schedule-exceptions` | doctor.manage / schedule.read | holiday / leave; flags bookings |
| `POST/GET /patients`, `GET/PATCH /patients/{id}` | patient.write / patient.read | |
| `POST /appointments`, `GET /appointments?day&doctor_id` | appointment.book / .read | |
| `POST /appointments/{id}/reschedule` · `/cancel` · `/status` | appointment.book / .status | |
| `POST /queue/tokens {doctor_id, patient_id?, phone?}` | queue.issue | walk-in token (BR-5), idempotent per patient |
| `GET /queue?doctor_id&day` | schedule.read | sessions with entries, people ahead, ETA |
| `POST /queue/sessions/{id}/next` · `/complete-current` | queue.operate | Next completes the current patient |
| `POST /queue/entries/{id}/{skip,recall,cancel}` | queue.operate | recall → called next |
| `GET /public/queue/{code}` | none (link is the capability) | token, current, ahead, ETA, doctor name — no PII |
| `WS /ws` then `{"type":"auth","token":…}` | access token | signals `queue.updated`; refetch via REST |
| `GET /inbox?status=open` | inbox.handle | handed-over chats, emergencies first, `can_reply` = inside 24 h window |
| `GET /inbox/conversations/{id}/messages` | inbox.handle | full thread (FR-8.1) |
| `POST /inbox/conversations/{id}/reply {text}` | inbox.handle | lands in the same WhatsApp chat; 422 `outside_24h_window` |
| `POST /inbox/conversations/{id}/hand-back` | inbox.handle | assistant resumes (FR-8.4) |
| `GET/POST /webhooks/whatsapp` | Meta (verify token / HMAC) | persist → enqueue → 200 |
| `POST /patients/{id}/consents {purpose, granted}` | patient.write | desk-recorded reminders/recalls consent (DP-2) |
| `POST /appointments/{id}/followup {kind: days\|rule\|plan, ...}` | appointment.status | one-tap follow-up (FR-6.2) |
| `GET /recall/rules` · `PUT /recall/rules/{visit_type}` | patient.read · recall_rules.manage | FR-6.1 |
| `GET /recalls?status=` | patient.read | recall list with lifecycle status |
| `GET /reports/revenue?month=YYYY-MM` | reports.read (owner) | FR-7.3 / AC-11, always `estimated: true` |
| `GET /dashboard/today?day=` | appointment.read | FR-7.1 per-doctor counts (doctors: own row) |
| `GET /patients/{id}/appointments` | patient.read | FR-7.2 history + upcoming |
| `GET /audit?entity_type&entity_id` | audit.read (owner) | |
| `GET /missed-calls?day&status=` · `POST /missed-calls {phone}` | calls.handle | FR-3.4 list / manual entry |
| `POST /missed-calls/{id}/resolve {outcome: called_back\|booked_by_phone\|no_answer\|not_needed}` | calls.handle | |
| `GET/POST /webhooks/exotel/{secret}` | Exotel (secret path; not in OpenAPI) | persist (`CallSid`) → enqueue → 200 |
| `GET /clinic/usage` | clinic.read | FR-9.1 plan, status, days left, usage + 80/100 % levels |
| `GET /admin/clinics` | platform admin (`pa` claim) | FR-9.4 counts only (DP-10) |
| `POST /admin/clinics/{id}/extend-trial {days}` · `/plan {plan}` · `/suspend {reason}` · `/reactivate` | platform admin | audited |

## Errors
`{"error": {"code", "message", "details"}}`

| HTTP | code | Meaning |
|---|---|---|
| 401 | unauthorized, otp_invalid, refresh_invalid, refresh_reused, refresh_expired | |
| 403 | clinic_suspended (any write while suspended), permission_denied, no_clinic_selected, forbidden_or_not_found, not_own_appointment, not_own_queue | other-tenant ids → `forbidden_or_not_found` (AC-10) |
| 409 | slot_taken, slug_taken, already_member, patient_exists | `slot_taken` → refetch slots (AC-2) |
| 422 | validation_error, slot_in_past, beyond_horizon, invalid_slot, change_cutoff_passed, max_upcoming_reached, invalid_transition, not_appointment_day, too_early_for_no_show, same_slot, doctor_inactive, token_window_not_open, session_ended, no_session, token_limit_reached, no_current_patient, outside_24h_window, visit_not_done, unknown_visit_type | |
| 429 | otp_rate_limited | |
