# Security & Privacy Model

> The FRD's DPDP statements are product requirements. Nothing here claims legal compliance; obligations (timelines, consent for minors, breach notice content) must be confirmed against the DPDP Act 2023 and DPDP Rules 2025 by counsel before pilot.

## Authentication (NFR-10)
* Staff sign in with mobile OTP. OTP: 6 digits, stored as HMAC-SHA256 (pepper from secret), 5-minute TTL, max 5 attempts per challenge, rate limits: 3 sends / 10 min / phone and 20 / hour / IP (Redis token bucket; DB fallback).
* Access token: JWT HS256 (key from env, rotated via `kid`), 15 min, claims `sub, sid, clinic_id, role, typ=access`.
* Refresh token: opaque 256-bit random, stored as SHA-256 hash, 30-day family. **Rotation on every use; reuse of a rotated token revokes the whole family** (theft detection), except within a 30 s grace window after rotation (benign reload/multi-tab race, ADR-0007).
* Clinic switch issues a new access token for that membership.

## Authorization
* RBAC matrix (FRD §3) in `core/rbac.py` as permission sets; endpoints declare `require(Permission.X)`.
* Tenant comes **only** from the verified token's `clinic_id`, never from a URL/body. Resource lookups are `WHERE clinic_id = :ctx AND id = :id`; any id not visible to the caller's tenant returns **403** and writes an `access_denied` audit row (AC-10). Because the lookup is scoped, another clinic's id and a nonexistent id are indistinguishable — no existence oracle.
* Defence in depth: Postgres RLS (ADR-002). A bug in a query filter still returns zero rows.
* Doctors see only their own schedule/queue where the FRD says "own".
* Platform admin: separate permission set; reading conversations requires an active `support_access_grants` row created from a clinic's support ticket, time-boxed (DP-10). All admin reads are audited.

## Data protection
* DP-5: AWS ap-south-1 only; EBS/RDS/S3 encryption (KMS); TLS 1.2+ at Nginx (Mozilla intermediate); HSTS.
* DP-7: LLM gets the current message + minimal state (doctor names, dates offered). Phone numbers, names and ages are replaced with placeholders by `assistant/redaction.py` before any provider call. Providers configured for zero data retention / no training where offered; documented per provider in integration-design.
* DP-9: retention job anonymises messages older than 12 months unless `clinics.settings.retention_override` with reason.
* Secrets only via environment / AWS SSM; `.env` never committed; `.env.example` has placeholders.
* Webhooks: Meta `X-Hub-Signature-256` HMAC, Razorpay signature, Exotel shared-secret + IP allowlist at Nginx.
* Logging: structlog JSON; phone numbers masked (`+91******3210`); message bodies never logged at INFO.

## Patient-facing safety (BR-10, FR-2.6, FR-8.3)
Deterministic emergency/medical keyword screen runs **before** any LLM call; LLM safety classification is a second layer. Emergency reply is a fixed template (clinic phone + "call 108/112") and never claims the AI contacted anyone.

## OWASP Top 10 checklist
Tracked in `docs/runbooks/release-checklist.md` (to be written in Phase 8).
