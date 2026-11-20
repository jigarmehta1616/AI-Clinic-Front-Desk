# Deployment

Target: AWS **ap-south-1 (Mumbai)** only (DP-5). **No staging or production deploy without explicit human approval.**
Nothing has been deployed yet; the production stack has only been built and run locally (see "Verified").

## Pilot topology (5 clinics)
* 1 × EC2 (t4g.medium or similar) running `infrastructure/docker/docker-compose.prod.yml`:
  `web` (Nginx: TLS, dashboard, `/api` proxy, `/api/v1/ws` upgrade, rate limits) · `api` (2 uvicorn workers) ·
  `worker` (ARQ) · `redis` (AOF) · one-shot `migrate` (runs before `api`/`worker` start).
* PostgreSQL: Amazon RDS for PostgreSQL 16 (Single-AZ for pilot), storage encrypted (KMS), automated backups 7 days +
  PITR (NFR-11). Create the roles once with the statements in `infrastructure/docker/postgres/init.sh`: runtime role
  `clinicdesk_app` (NOBYPASSRLS) in `DATABASE_URL`, schema owner `clinicdesk_owner` in `MIGRATION_DATABASE_URL`.
* TLS: Let's Encrypt certificate on the host (`fullchain.pem`, `privkey.pem`) mounted read-only via `TLS_CERT_DIR`;
  TLS 1.2/1.3 only, HSTS, CSP, no server tokens.
* Secrets: AWS SSM Parameter Store → env file on the host at deploy time (root-only, never in images or git).
* Observability: container JSON logs (rotated) → CloudWatch agent; Sentry (PII scrubbing). Langfuse residency still open.

## Images
| Image | Dockerfile | Notes |
|---|---|---|
| `clinicdesk-api` | `infrastructure/docker/Dockerfile.api` | python:3.12-slim, non-root uid 10001, read-only rootfs in compose, ships Alembic migrations, healthcheck `/api/v1/health` (checks the DB) |
| `clinicdesk-web` | `infrastructure/docker/Dockerfile.web` | Vite build → nginx:1.27-alpine; config from `infrastructure/nginx/` |

Edge rules (`infrastructure/nginx/default.conf.template`):
* HTTP → HTTPS redirect; `/healthz` on port 80 for the load balancer.
* Per-IP rate limits: OTP request/verify 5 req/min (burst 5/10), webhooks 30 req/s, other API 20 req/s → 429.
  The API keeps its own per-phone OTP limit.
* `X-Forwarded-For` is overwritten with the client address (never appended); uvicorn trusts proxy headers because
  the API port is not published.
* Webhook access logs are off: the Exotel secret is part of the path.
* `/assets/*` cached for a year (hashed names); `index.html` `no-cache`; SPA fallback for every other path.

## Environment file
Start from `.env.example`. Compose-only variables: `SERVER_NAME` (also sets `CORS_ORIGINS` and `PUBLIC_BASE_URL`),
`TLS_CERT_DIR`, `HTTP_PORT`/`HTTPS_PORT` (default 80/443), `IMAGE_TAG`. With `ENV=production` the API refuses to
start unless `OTP_PROVIDER` is not `console`, `WHATSAPP_PROVIDER=cloud` with app secret + access token, and
`PRIVACY_NOTICE_URL` is real.

## Release steps
1. CI green on `main` (no skipped integration tests).
2. Build images tagged by git SHA (`IMAGE_TAG=<sha>`); push to ECR (ap-south-1).
3. **Human approval.** Take an RDS snapshot.
4. On the host:
   `docker compose -f infrastructure/docker/docker-compose.prod.yml --env-file /etc/clinicdesk/prod.env up -d`
   (`migrate` runs first; `api` waits for it, `web` waits for a healthy `api`).
5. Smoke: `/healthz`, `/api/v1/health`, sign-in, a WebSocket connects, Meta webhook verification, one Exotel test call.
6. Rollback: redeploy the previous `IMAGE_TAG`. Migrations are forward-only in production; restore from the snapshot
   only with approval.

## Exotel setup (per clinic, FR-3.1)
1. Buy an Exophone; save it on the clinic (Settings → "Missed-call number").
2. Call flow: Connect to the clinic phone → on no-answer/busy → Passthru applet to
   `https://<SERVER_NAME>/api/v1/webhooks/exotel/<EXOTEL_WEBHOOK_SECRET>`.
3. The clinic's carrier forwards unanswered/busy calls to the Exophone (onboarding runbook).
4. The Meta template `missed_call_offer` (gu/hi/en, two quick replies) must be approved before go-live.

## Platform admin
`scripts/make_platform_admin.py <+91 phone> [--revoke]` (run with the owner DB URL; audited). It takes effect at the
user's next sign-in. Admins see clinic counts and plans only, never conversations or patients (DP-10).

## Verified (local, 2026-11-20)
Built both images and ran the stack with a self-signed cert against the local Postgres (`ENV=staging`):
migrate exited 0; api healthy; HTTP→HTTPS 301; security headers present; asset/index cache headers correct;
`/api/v1/health` ok; OTP per-IP limit returns 429; OTP sign-in sets the refresh cookie `HttpOnly; Secure;
SameSite=strict; Path=/api/v1/auth`; an authenticated WebSocket through Nginx gets `ready`; an Exotel webhook through
Nginx was processed by the containerised worker (offer sent by the dev WhatsApp sender); the secret was absent from
Nginx logs; a wrong secret returns 404.
Not verified: a real domain/Let's Encrypt, RDS, ECR, CloudWatch, Sentry, real WhatsApp or Exotel.

## Open
* Langfuse data residency (DP-5/DP-7). * WhatsApp Cloud API data residency is Meta-controlled — document in DPA (DP-4).
* Exotel source-IP allowlist (Exotel publishes its ranges) in addition to the secret path.
* CI job that builds both images and runs this smoke test.
