# Requirements Traceability Matrix

Source: `docs/source/FRD.docx` (FRD v0.1, 20 Nov 2026). IDs are preserved verbatim.
Status legend: **—** not started · **D** designed · **I** implemented · **U** pure rule unit-tested & passing · **IT✔** integration test passing on real PostgreSQL 16 (RLS-subject role) · **UI✔** screen built and exercised in a browser against the real API · **T** all tests passing · **V** verified on staging.
Last updated: 2026-11-20 (M5 web dashboard: 231 API + 16 web tests).
Module codes map to `apps/api/src/clinicdesk/modules/<module>`.

| Code | Module |
|---|---|
| auth | Authentication & RBAC |
| tenancy | Clinics, staff, settings, tenant isolation |
| scheduling | Doctors, sessions, holidays/leave, slot computation |
| patients | Patients, family members, consent |
| booking | Appointments (book/reschedule/cancel/arrive/no-show) |
| queue | Walk-in tokens, merged queue, live updates |
| messaging | WhatsApp in/out, templates, outbox, 24h window |
| assistant | LangGraph agent, NLU, safety, button fallback |
| calls | Missed-call recovery (Exotel) |
| reminders | Reminders, quiet hours, no-show rebook |
| recall | Recall rules, follow-ups, treatment plans |
| inbox | Staff handover inbox |
| reports | Revenue attribution, today view, trends |
| billing | Plans, usage, Razorpay |
| audit | Audit log, DSR, retention, breach |

## Functional requirements (51)

| ID | Pri | Summary | Module | Tests (planned) | Status |
|---|---|---|---|---|---|
| FR-1.1 | P0 | Owner OTP sign-up, clinic profile (name, address, map, specialty, languages, fees) | auth, tenancy | test_auth_otp, test_clinic_profile | I (OTP sign-up + onboarding screen) · IT✔ · UI✔ |
| FR-1.2 | P0 | Doctors with weekly sessions, slot length, max tokens | scheduling | test_slots, test_doctor_api | I (doctors + weekly sessions editor) · U · IT✔ · UI✔ |
| FR-1.3 | P0 | Holidays/leave; affected bookings flagged | scheduling, booking | test_leave_flags_bookings | I (holiday/leave dialog; flagged bookings shown) · U · IT✔ · UI✔ |
| FR-1.4 | P0 | Invite staff by mobile + role | tenancy, auth | test_staff_invite | I (invite staff screen; notification pending) · IT✔ · UI✔ |
| FR-1.5 | P0 | Connect WhatsApp number or shared pilot number | messaging, tenancy | test_tenant_resolution | I (own number via `wa_phone_number_id`; shared pilot number + `#CODE`) · IT✔ — Meta embedded signup pending |
| FR-1.6 | P0 | Specialty template pre-fills recall rules + templates | recall, tenancy | test_specialty_templates | I (dental + physio rules seeded at onboarding) · U · IT✔ |
| FR-1.7 | P1 | Live in < 30 min | web onboarding | manual (pilot) | I partial (3-step onboarding flow); 30-min target to validate in pilot |
| FR-2.1 | P0 | Book in gu/hi/en/mixed | assistant | test_nlu_fixtures, AC-1 | I (deterministic gu/hi/en/mixed; LLM in M4) · U · IT✔ |
| FR-2.2 | P0 | Offer next 3–5 free slots, one-tap pick | assistant, scheduling | test_slot_offer | I · U · IT✔ (3–5 slots + other day) |
| FR-2.3 | P0 | Collect name/age for new; recognise returning by number | assistant, patients | test_patient_resolution | I · IT✔ (new: name+age; returning by number) |
| FR-2.4 | P0 | Reschedule/cancel; slot freed at once | booking | test_reschedule_frees_slot | I (API + WhatsApp) · IT✔ |
| FR-2.5 | P0 | FAQ from clinic profile | assistant | test_faq_tool | I (timings, address, map, phone, fee) · IT✔ (smoke) |
| FR-2.6 | P0 | Medical/complaint/emergency/unclear → staff; no medical advice | assistant, inbox | test_safety_classifier | I (medical/complaint/unclear → staff) · U · IT✔ |
| FR-2.7 | P1 | Voice notes (STT) | assistant | test_stt_adapter | — |
| FR-2.8 | P1 | Book for family member under same number | patients, booking | test_family_booking | I (pick family member / someone else) · IT✔ partial |
| FR-2.9 | P0 | STOP opt-out of reminders/recalls | patients, messaging | test_opt_out, AC-9 | I · U · IT✔ |
| FR-3.1 | P0 | Unanswered calls forwarded to Exotel virtual number | calls | test_calls_admin_integration | I (`/webhooks/exotel/{secret}`, clinic by `exotel_number`, answered calls ignored) · IT✔ — not yet against real Exotel |
| FR-3.2 | P0 | WhatsApp offer within 60 s of missed call | calls, messaging | test_missed_call_message, AC-3 | I (`missed_call_offer` template + Book / Call me back buttons, job wake-up) · IT✔ (AC-3) — 60 s not measured on real WhatsApp |
| FR-3.3 | P1 | SMS with booking link if no WhatsApp / no reply in 15 min | calls | test_sms_fallback | — |
| FR-3.4 | P0 | Missed-call list: recovered / pending / call back needed | calls | test_missed_call_status | I (pending / call_back_needed after 15 min no reply / recovered on booking / resolved) · U · IT✔ · web ✔ |
| FR-3.5 | P0 | Repeat calls within 30 min → one message | calls | test_missed_call_dedup | I (one row per 30-min burst, repeat_count) · U · IT✔ |
| FR-4.1 | P0 | Walk-in token via QR, WhatsApp or receptionist | queue | test_issue_token | I (dashboard + WhatsApp; QR = wa.me link with #CODE) · U · IT✔ |
| FR-4.2 | P0 | Patient sees token, current token, wait estimate, live | queue | test_queue_status | I (public link page /t/:code + WhatsApp status; no PII) · U · IT✔ · UI✔ |
| FR-4.3 | P0 | Alert when N (default 3) ahead | queue, messaging | test_ahead_alert | I (once per token, ≤ N ahead, template outside window) · IT✔ |
| FR-4.4 | P0 | "Next" calls next token; skipped tokens recallable | queue | test_call_next, test_skip_recall | I (queue screen: Next, skip, recall, remove) · U · IT✔ · UI✔ |
| FR-4.5 | P1 | TV display with audio announcements | web | e2e_tv_display | — |
| FR-4.6 | P0 | Booked + walk-in merged into one ordered queue | queue | test_queue_order (BR-6) | I · U · IT✔ |
| FR-4.7 | P1 | Wait estimate from doctor's 30-day average consult time | queue | test_wait_estimate | I · U (30-day avg, ≥10 samples else slot length) |
| FR-5.1 | P0 | Reminders 24 h and 2 h before, Confirm/Reschedule/Cancel buttons | reminders | test_reminder_schedule | I (24 h + 2 h, Confirm/Reschedule/Cancel, consent + quiet-hours aware) · U · IT✔ |
| FR-5.2 | P0 | Unmarked at session end → no-show | booking, reminders | test_noshow_sweep, AC-6 | I (manual + automatic sweep) · IT✔ |
| FR-5.3 | P0 | No-show rebook message same day | reminders | test_noshow_rebook | I (consented, quiet-hours aware, one-tap rebook) · IT✔ |
| FR-5.4 | P1 | Waitlist offered freed slots | booking | test_waitlist | — |
| FR-6.1 | P0 | Recall rules per visit type (trigger, delay, message, follow-ups) | recall | test_recall_rules | I (rules per visit type, editable; auto recall on completion) · IT✔ |
| FR-6.2 | P0 | One-tap follow-up after visit | recall | test_set_followup | I (one-tap: review in N days, rule, plan N sessions) · IT✔ |
| FR-6.3 | P0 | Recall at due date with one-tap booking | recall | test_recall_send, AC-7 | I (due date 10:00 clinic time, one-tap Book now / Not now) · IT✔ |
| FR-6.4 | P0 | Up to 2 follow-ups (3 and 7 days), then lapsed | recall | test_recall_followups_lapse | I (+3 d, +7 d relative to first send, then lapsed) · U · IT✔ |
| FR-6.5 | P1 | Treatment plan done vs planned, dropout flag | recall | test_plan_dropout | I partial (plan sessions done/planned, completes; dropout flag + UI pending) |
| FR-6.6 | P1 | CSV import of past patients | patients, recall | test_csv_import | — |
| FR-7.1 | P0 | Today view per doctor | reports | test_today_view | I (Today view: per-doctor counts, tokens, open chats, emergencies) · IT✔ · UI✔ |
| FR-7.2 | P0 | Patient list: search, history, upcoming, recall status | patients | test_patient_search | I (search, profile, visit history, upcoming, recalls, consent) · IT✔ · UI✔ |
| FR-7.3 | P0 | Monthly revenue recovered by source × fee | reports | test_revenue_report, AC-11 | I (by source × fee, labelled estimated; revenue screen) · IT✔ · UI✔ |
| FR-7.4 | P1 | Monthly WhatsApp summary + PDF on 1st | reports | test_monthly_report_job | — |
| FR-7.5 | P1 | Weekly trends | reports | test_trends | — |
| FR-8.1 | P0 | Shared inbox with full conversation + reason tag | inbox | test_handover | I (inbox list, emergencies first, full thread) · IT✔ · UI✔ |
| FR-8.2 | P0 | Staff reply lands in same WhatsApp chat | inbox, messaging | test_staff_reply | I (staff reply; 24 h window enforced) · IT✔ · UI✔ |
| FR-8.3 | P0 | Emergency words → immediate reply + staff alert | assistant, inbox | test_emergency, AC-8 | I · U · IT✔ |
| FR-8.4 | P1 | Hand chat back to assistant | inbox | test_handback | I (hand back) · IT✔ · UI✔ |
| FR-9.1 | P0 | Free pilot plan; days left + usage | billing | test_plan_usage | I (pilot plan, days left, monthly messages, doctors, patients) · IT✔ · web ✔ |
| FR-9.2 | P1 | Razorpay monthly subscription + GST invoice | billing | test_razorpay_webhook | — |
| FR-9.3 | P1 | Usage limits; warn at 80 % / 100 % | billing | test_usage_limits | P (80 % / 100 % levels shown; limits not enforced — needs product decision) |
| FR-9.4 | P0 | Platform admin: extend trial, change plan, suspend | billing, tenancy | test_platform_admin | I (`/admin/clinics`: extend trial, plan, suspend/reactivate; audited; suspended → writes 403 + WhatsApp ignored) · IT✔ · web ✔ |

## Business rules

| ID | Rule (short) | Enforcement point | Tests | Status |
|---|---|---|---|---|
| BR-1 | One confirmed booking per slot, DB lock | Partial unique index `uq_appt_active_slot` + transaction | test_concurrent_last_slot (AC-2) | I · IT✔ |
| BR-2 | Book ≤ 14 days ahead (1–60 configurable) | `booking.policy` | test_booking_horizon | I · U · IT✔ |
| BR-3 | Reschedule/cancel until 1 h before (configurable) | `booking.policy` | test_cancel_cutoff | I · U · IT✔ |
| BR-4 | ≤ 2 upcoming bookings per phone per doctor | advisory xact lock + count | test_max_upcoming_concurrent | I · U · IT✔ |
| BR-5 | Walk-in tokens only during/≤1 h before session, ≤ token limit | `queue.policy` + row lock on session-day | test_token_window_limit | I · U · IT✔ |
| BR-6 | Arrived booked keep slot order; walk-ins fill gaps by arrival | `queue.ordering` (pure) | test_queue_order | I · U · IT✔ |
| BR-7 | No promo/recall 21:00–08:00 IST; reminders wait to 08:00 | `messaging.quiet_hours` (pure) | test_quiet_hours | I (dispatcher defers non-transactional) · U · IT✔ |
| BR-8 | ≤ 1 recall / clinic / 3 days; none after opt-out | `recall.policy` + send-time recheck | test_recall_rate_limit | I (opt-out, explicit recall consent, 1 recall / 3 days) · U · IT✔ |
| BR-9 | Outside 24 h window → approved templates only | `messaging.window` at send time | test_template_window | I (session msg in window, else approved template, else fail) · U · IT✔ |
| BR-10 | Never diagnose/prescribe/interpret/comment on symptoms | `assistant.safety` (deterministic + LLM) | test_safety_classifier | I (lexicon screen, no free-text answers) · U · IT✔ |
| BR-11 | Recovered only if arrived / token completed | `reports.attribution` | test_attribution_requires_arrival | I (counted on arrival only, booking within 7 d of message) · U · IT✔ |
| BR-12 | Revenue = recovered visits × doctor fee; labelled estimate | `reports.revenue` | test_revenue_estimate | I (doctor fee, else clinic default; snapshotted; estimate label) · U · IT✔ |
| BR-13 | Audit every booking/cancel/status change (actor, channel, time) | `audit.record` in same transaction | test_audit_completeness | I · IT✔ (booking/cancel/status/reschedule/leave) |

## Privacy (DP) requirements

| ID | Summary | Enforcement | Tests | Status |
|---|---|---|---|---|
| DP-1 | Consent notice before booking, in patient's language | assistant consent gate | test_consent_gate | I (notice + link + Agree before any booking) · IT✔ |
| DP-2 | Reminder/recall consent separate, timestamp + channel | `consent_events` table | test_consent_history | I (separate reminders/recalls consent, history) · IT✔ |
| DP-3 | Access/correct/delete via WhatsApp, routed to clinic, SLA | `audit.dsr` | test_dsr_flow | — |
| DP-4 | Clinic = Fiduciary, ClinicDesk = Processor (DPA) | contractual + docs | n/a (legal) | — |
| DP-5 | India region, TLS 1.2+, encryption at rest | infra (ap-south-1, EBS/RDS encryption, Nginx TLS) | deploy checklist | P (Nginx TLS 1.2+/HSTS in `infrastructure/nginx`; region + RDS/EBS encryption are deploy steps) |
| DP-6 | Every query scoped by clinic; tests prove isolation | repo scoping + Postgres RLS | test_cross_tenant (AC-10) | I (scoping + forced RLS) · IT✔ |
| DP-7 | LLM input minimised, phones masked, no-training provider | `assistant.redaction` | test_llm_redaction | — |
| DP-8 | Breach: clinics at once, Board within 72 h | runbook + `breach_incidents` | runbook drill | — |
| DP-9 | Conversation logs > 12 months deleted/anonymised | retention job | test_retention_job | — |
| DP-10 | RBAC + access logging; admin needs support ticket to read chats | `support_access_grants` | test_admin_conversation_access | D (RBAC done; support grants pending) |

## Non-functional requirements

| ID | Target | Approach | Verification | Status |
|---|---|---|---|---|
| NFR-1 | 95 % replies ≤ 5 s | async pipeline, small model, deterministic paths | load test + Langfuse latency | I (webhook ack 17 ms; reply dispatched 0.8 s — one local sample, not load-tested) |
| NFR-2 | Queue updates ≤ 2 s | Postgres commit → Redis pub/sub → WebSocket | e2e timing test | I · IT✔; measured locally: WhatsApp emergency → dashboard badge 0.94 s, staff reply visible 0.22 s (single samples, not a load test) |
| NFR-3 | 99.5 % uptime 08–22 IST | health checks, restart policies, runbooks | uptime monitor | — |
| NFR-4 | Webhooks queued + retried, no loss | persist-then-ack inbound events, DB outbox | test_webhook_durability | I (persist-then-ack, dedup, durable jobs, at-most-once send) · IT✔ |
| NFR-5 | Jobs within 5 min | DB `scheduled_jobs` + 1-min poller, SKIP LOCKED | test_scheduler_latency | I (DB jobs, 1-min tick, SKIP LOCKED, backoff) · U · IT✔ |
| NFR-6 | 200 clinics / 50k patients / 20k msg/day | indexes, pooling; load test | k6/locust run | — |
| NFR-7 | Untrained receptionist productive in 10 min | UX of top-6 actions | pilot usability session | D (top actions ≤ 2 taps from Today) — needs a pilot usability session |
| NFR-8 | Chrome desktop, Android tablet/phone, TV browser | responsive UI | e2e viewports | I (no horizontal overflow at 375 / 768 / 1280 px on every screen; drawer < 1024 px) — TV display (P1) pending |
| NFR-9 | gu/hi/en patient messaging; dashboard en (gu P1) | i18n template catalogue | test_templates_all_languages | I (catalogue gu/hi/en, completeness tested; native review pending) · U |
| NFR-10 | JWT + refresh rotation, RBAC, OTP rate limits, OWASP | auth module | test_refresh_rotation, test_otp_rate_limit | I (OTP+JWT+rotation with 30 s reuse grace+RBAC; per-IP limits on OTP/webhooks/API in Nginx) · U · IT✔ · edge smoke-tested |
| NFR-11 | Langfuse traces + cost, Sentry, daily backup + 7-day PITR | observability module, backup runbook | restore drill | — |
| NFR-12 | < ₹500 / active clinic / month | cost telemetry per clinic | monthly cost report | — |

## Acceptance criteria (staging, real WhatsApp number)

| ID | Scenario | Automated proxy test | Status |
|---|---|---|---|
| AC-1 | "appointment kal savare" → morning slots, ≤ 6 messages | test_ac1_booking_conversation | IT✔ (5 replies to booked; real-number staging run pending) |
| AC-2 | Two patients tap same last slot | test_concurrent_last_slot | IT✔ (API + WhatsApp) |
| AC-3 | Missed call → WhatsApp ≤ 60 s, in list | test_ac3_missed_call | — |
| AC-4 | "Reschedule" on 24 h reminder → slots, old freed, audited | test_ac4_reschedule_from_reminder | IT✔ (WhatsApp + from 24 h reminder) |
| AC-5 | QR walk-in → token + estimate ≤ 5 s; alert at 3 ahead | test_ac5_walkin | — |
| AC-6 | Unmarked → no-show at session end, rebook same day | test_ac6_noshow | IT✔ (no-show + rebook) |
| AC-7 | Recall in 6 months → sent ≥ 08:00 on due date; recovered on arrival | test_ac7_recall | IT✔ (due date, ≥ 08:00, one tap, counted on arrival) |
| AC-8 | "chest pain" → emergency reply + staff alert, no AI medical answer | test_ac8_emergency | IT✔ (en + gu) |
| AC-9 | STOP → no reminders/recalls, opt-out recorded | test_ac9_stop | IT✔ |
| AC-10 | Clinic A staff → Clinic B patient API → 403 + logged | test_ac10_cross_tenant | IT✔ (test_cross_tenant_patient_access_is_403_and_logged) |
| AC-11 | Month end → recovered by source + estimated revenue | test_ac11_monthly_report | IT✔ (by source + estimated revenue; tenant-isolated; owner only) |
