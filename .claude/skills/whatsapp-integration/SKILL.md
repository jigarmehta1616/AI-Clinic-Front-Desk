---
name: whatsapp-integration
description: WhatsApp Cloud API webhooks, signatures, templates, 24-hour window, outbox delivery and retries. Use for any inbound or outbound WhatsApp work.
---
# WhatsApp integration
**Purpose** Never lose, duplicate or mis-send a patient message.
**When to use** Webhooks, sends, templates, delivery statuses.
**Required context** `docs/architecture/integration-design.md`, ADR-0004, `integrations/whatsapp/`, `modules/messaging/`.

## Engineering rules
- Webhook: verify `X-Hub-Signature-256` over the raw body → insert `inbound_events` (unique provider + external_id) → enqueue → return 200. No processing inside the request.
- Every send is an `outbox_messages` row with a deterministic `idempotency_key` (e.g. `reminder24:{appointment_id}`).
- 24 h window from `conversations.last_inbound_at`; outside it only approved templates (BR-9).
- Category drives quiet hours (BR-7): transactional replies exempt; reminders deferred to 08:00; recall/promo never 21:00–08:00.
- Opt-out is checked at dispatch time, not just schedule time (BR-8, AC-9).
- Retry 429/5xx/timeouts with backoff; never retry policy 4xx. Status webhooks are deduplicated too.
- Interactive: ≤ 3 reply buttons, list ≤ 10 rows; structured payload ids (`slot:<iso>`, `appt:<id>:cancel`).

## Validation checklist
- [ ] Duplicate webhook test  - [ ] Duplicate outbox/job test  - [ ] Template present in gu/hi/en
