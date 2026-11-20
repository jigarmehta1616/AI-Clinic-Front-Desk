# Project status

_Persistent source of progress. Update at every milestone. Last update: 2026-11-20._

## Milestones
| # | Milestone | State |
|---|---|---|
| M0 | Repo audit, FRD extraction, traceability, architecture, ADRs, skills, CLAUDE.md | ✅ done |
| M1 | Backend foundation: config, DB + RLS, migrations, auth (OTP/JWT/rotation), RBAC, clinics/staff, doctors/sessions/leave, slots, patients, booking (BR-1..4), audit | ✅ done — integration-verified |
| M2 | Queue (tokens BR-5, merged ordering BR-6, next/skip/recall, public tracking, WebSocket signals), durable scheduled jobs + worker, automatic no-show sweep | ✅ done — integration-verified (FR-4.3 alert + FR-5.3 rebook message wait for M3) |
| M3 | WhatsApp webhook/outbox/dispatcher, consent (DP-1/2), STOP/START, emergency + medical safety, deterministic gu/hi/en assistant (book, reschedule, cancel, token, status, FAQ), staff inbox, no-show rebook (FR-5.3), queue alerts (FR-4.3) | ✅ done — integration-verified against a fake Meta client; **not yet against real WhatsApp** |
| M4 | Reminders 24 h / 2 h (FR-5.1), recall engine + dental/physio templates + follow-ups + 3-day cap (FR-6.x, FR-1.6, BR-8), treatment plans, revenue attribution + monthly report (BR-11/12, FR-7.3, AC-7, AC-11) | ✅ done — integration-verified; **LLM NLU fallback deferred** (needs provider + key decision) |
| M4b | LangGraph NLU fallback behind the deterministic layer (DP-7 redaction, Langfuse tracing, gu/hi/en eval fixtures) | needs decision: OpenAI vs Gemini, API key, no-training settings |
| M5 | Web dashboard: sign-in/onboarding, Today, appointments + booking, live queue, patients + profile, inbox, recall + rules, revenue, doctors + schedules, settings + staff, public token page | ✅ done — 16 web tests, browser-verified at 3 widths against the real API |
| M6 | Exotel missed-call recovery (FR-3.1/3.2/3.4/3.5), pilot plan usage (FR-9.1/9.3 warnings), platform admin + suspension (FR-9.4), production images + Nginx + compose | ✅ done — integration-verified, browser-verified, prod stack run locally; **not deployed**, not yet against real Exotel |
| M7 | Staging deploy on AWS Mumbai (needs approval + AWS account), CI image build + smoke, real WhatsApp/Exotel end-to-end, Razorpay (FR-9.2, P1) | — |

## Verified facts (2026-11-20)
* Postgres 16.6 (5433) + Redis 7.4 (6380) in Docker; migrations 0001–0005; forced RLS on every tenant table (incl. `missed_calls`).
* API: `pytest apps/api/tests` **264 passed, 0 warnings** (unit + integration). ruff, format clean; mypy (run from `apps/api`) **0 issues in 94 files**.
* Web (`apps/web`): typecheck, ESLint, **18 vitest tests**, production build.
* M6 browser walkthrough: Exotel number saved in Settings; simulated Exotel call → offer sent → listed under "Waiting on WhatsApp";
  usage card; admin console (list, suspend → red banner on every screen, staff write refused with `clinic_suspended`,
  call while suspended ignored, reactivate → back to trial). No horizontal overflow at 375 px.
* Production stack run locally (details in `docs/deployment.md` → Verified): TLS edge, headers, rate limits, Secure
  refresh cookie, WebSocket through Nginx, webhook → containerised worker.
* Browser walkthrough (built-in browser, real API + worker + Redis, `scripts/seed_demo.py` data): sign-in via OTP,
  Today, call next, booking dialog end-to-end, queue, patients, profile, inbox thread + staff reply + hand-back, recall,
  revenue, doctors, settings, public token page (no PII). No horizontal overflow at 375 / 768 / 1280 px.
* Live updates (NFR-2), local single samples: WhatsApp emergency → dashboard badge 0.94 s; staff reply visible 0.22 s.
* Bugs found by the walkthrough and fixed:
  - English messages were answered in the clinic's default language (Gujarati) → English cue words.
  - API stayed on 1-minute fallback after starting while Redis was down → self-healing lazy job wake-up.
  - Inbox thread crashed (effect returned the browser's scroll Promise) → fixed + error boundary per screen.
  - Staff replies didn't appear until reload (no signal after the worker sent) → `inbox.message` signal.
  - Reload during a token refresh logged the user out (reuse detection) → 30 s reuse grace (ADR-0007).
  - Web client: `/auth/me` and `/auth/select-clinic` skipped refresh-and-retry; stale single-flight refresh promise.

## Blockers / needs a human
1. **Meta WhatsApp Business**: app + WABA + test number, app secret, verify token, permanent access token; submit the
   templates in `docs/architecture/integration-design.md`. Until then all sending is the dev log provider.
2. **Native-speaker review** of every Gujarati/Hindi string in `modules/messaging/templates.py`.
3. **Clinician review** of the emergency/medical lexicons in `modules/assistant/text.py` (Q12, Q19).
4. Product decisions Q1–Q19 (`docs/architecture/system-design.md` §7); Q17 (reminders opt-in) also needs legal input.
5. A real privacy notice URL per clinic (DP-1) and the DPA (DP-4).
6. **Exotel** account + Exophone per clinic, and Meta approval of the `missed_call_offer` template.
7. **AWS** account access and explicit approval before any staging/production deploy.

## Known gaps / follow-ups in code
* `replace_sessions` does not flag existing bookings that fall outside the new weekly template.
* Staff invite does not notify the invitee (messaging exists now; needs an approved template).
* Voice notes (FR-2.7, P1) answered with "please type"; DSR requests via WhatsApp (DP-3) not yet routed.
* If an inbound turn fails 6 times the patient gets no reply (job visible as failed); add a fallback "staff will reply".
* `token_issued` template exists but receptionist-issued tokens don't message the patient yet.
* OTP per-IP limit is in Nginx (prod edge) only; the API itself limits per phone.
* Disabled membership: access token valid ≤ 15 min; open WebSocket keeps receiving signals (no data) until reconnect.
* Concurrent refresh from two tabs triggers reuse detection → web client must single-flight refresh.
* Specialty templates (FR-1.6) wait for the recall module (M4). TV display (FR-4.5, P1) not started.
* `scheduled_jobs` done-row pruning (30 days) not yet scheduled.
* Web: TV display (FR-4.5, P1), Gujarati dashboard (NFR-9, P1) not built.
* Missed calls: SMS fallback (FR-3.3, P1) not built; plan limits (FR-9.3) are shown, not enforced (product decision).
* Platform-admin claim changes apply at next sign-in/refresh; suspension status is cached up to 30 s per API process.
* Web: no Playwright E2E yet; browser checks were manual + scripted via the built-in browser.
* Monthly WhatsApp/PDF report to owner (FR-7.4, P1), weekly trends (FR-7.5, P1), CSV import (FR-6.6, P1) not started.
* Treatment-plan dropout flag (FR-6.5) not computed yet; plans are visible via recalls only (no plan endpoint).

## Next action
M7 needs a human first: approval + AWS account (ap-south-1) for staging, Meta WhatsApp credentials, an Exotel
account + Exophone. Without those: add a CI job that builds both images and runs the local smoke test, then
P1 items (FR-3.3 SMS fallback, FR-7.4 monthly report, FR-4.5 TV display). M4b still needs an LLM provider decision.
