# Integration Design

Each provider is an adapter implementing a protocol in `clinicdesk/integrations/`. Every adapter has a `Fake*` implementation used in tests and local dev **only**; fakes are never selectable when `ENV=production` (startup check).

| Provider | Protocol | Inbound | Outbound | Idempotency | Fallback (FRD §9) | Status |
|---|---|---|---|---|---|---|
| WhatsApp Cloud API (Meta, Graph API) | `WhatsAppClient` | `POST /webhooks/whatsapp` (HMAC), `GET` verify challenge | `/{phone_number_id}/messages` text, interactive list/buttons, template | inbound: `messages[].id`, statuses: `id+status`; outbound: outbox key | dashboard booking; SMS reminders | not connected — needs Meta app, WABA, test number |
| Exotel | `calls.service.handle_exotel` | `GET/POST /api/v1/webhooks/exotel/{EXOTEL_WEBHOOK_SECRET}` — Passthru applet after an unanswered Connect; reads `CallSid`, `CallFrom`, `CallTo` (the clinic's Exophone), `DialCallStatus` | secret path segment (constant-time compare; Nginx keeps it out of access logs) | `CallSid` in `inbound_events`; 30-min per-caller burst (FR-3.5) | manual missed-call entry on the dashboard | built + tested; not connected — needs account + Exophone |
| LLM (OpenAI / Gemini) | `LLMProvider.extract(schema, messages)` | — | structured output | n/a | button menu | not connected — needs API key |
| SMS (P1) | `SmsClient` | delivery reports | DLT-registered templates (India TRAI DLT) | outbox key | — | P1 |
| Razorpay (P1) | `BillingProvider` | `POST /webhooks/razorpay` (signature) | subscriptions API | `event.id` | manual invoice | P1 |
| STT (P1) | `SpeechToText` | — | — | — | ask to type/tap | P1 |

## WhatsApp specifics
* 24 h customer-service window: computed from `conversations.last_inbound_at`. Outside it only approved templates (BR-9). Template catalogue per language: `consent_notice`, `booking_confirmed`, `reminder_24h`, `reminder_2h`, `noshow_rebook`, `recall_due`, `recall_followup`, `missed_call_offer`, `token_alert`, `emergency_reply`, `monthly_report`.
* Retries: 429/5xx/network → backoff 30 s, 2 m, 10 m, 30 m, 2 h, 6 h; 4xx policy errors (e.g. 131047 re-engagement) → no retry, mark failed, alert inbox.
* Quality: honour opt-out instantly; caps BR-7/BR-8 protect number rating.

## India-specific
* SMS requires DLT registration of sender ID + templates — lead time; must start before P1.
* Exotel missed-call detection requires the clinic's carrier to forward on no-answer/busy to the Exotel number — clinic-side setup step in onboarding runbook.

## Meta templates to submit for approval (BR-9)
Business-initiated messages are sent as these templates outside the 24 h window, in gu, hi and en
(`modules/messaging/templates.py` → `META_TEMPLATES`; bodies = catalogue text with `{{n}}` params in order):

| Template | Params | Quick reply | Used by |
|---|---|---|---|
| `noshow_rebook` | clinic | `rebook:<appointment_id>` | FR-5.3 |
| `token_alert` | token, ahead | — | FR-4.3 |
| `token_issued` | token, doctor, ahead, wait, link | — | receptionist-issued token (future) |
| `staff_alert` | reason, phone, link | — | FR-8.3 alert to clinic phone |
| `appointment_reminder` (body = catalogue `reminder`) | clinic, doctor, date, time | `confirm:<id>`, `act:r\|<id>`, `act:c\|<id>` | FR-5.1 |
| `recall_due` | label, clinic | `recall:<id>`, `recall_no:<id>` | FR-6.3 |

## Current wiring (M3)
* `WHATSAPP_PROVIDER=log` (dev) logs instead of sending; `cloud` uses `CloudApiClient` (Graph API v21.0). Production refuses `log`.
* Webhook: `GET/POST /api/v1/webhooks/whatsapp` (verify token; HMAC `X-Hub-Signature-256` over raw body).
* Replies to one recipient are sent in order (outbox `seq`; the dispatcher waits for earlier pending replies).
* Dispatch is at-most-once: a row left in `sending` after a crash is marked `delivery_unknown`, never resent.
* **Not yet verified against Meta** — needs a WhatsApp Business app, WABA, test number, app secret, access token.
