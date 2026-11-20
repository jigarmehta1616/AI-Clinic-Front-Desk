# Testing Strategy

| Layer | Where | DB/Redis | Mocks | Run |
|---|---|---|---|---|
| Pure policies (BR-*) | `apps/api/tests/unit` | none | none | every change |
| Service + API integration | `apps/api/tests/integration` (`@pytest.mark.integration`) | real Postgres 16 as `clinicdesk_app` (RLS applies) | provider fakes only | every change touching services; CI |
| Concurrency | integration, `asyncio.gather` over separate pooled connections | real | — | CI |
| Security | integration: cross-tenant, RLS raw SQL, append-only audit, RBAC per role, token reuse | real | — | CI |
| Assistant NLU | `tests/assistant/fixtures/*.yaml` (gu/hi/en/mixed) | — | real LLM in nightly job; deterministic layers in CI | nightly |
| Frontend | Vitest + Testing Library; Playwright E2E for top receptionist flows | staging-like | API | CI / pre-release |
| Load | k6/locust scripts in `tests/load` (Phase 8) | staging | — | before pilot |
| Acceptance AC-1..11 | automated proxies + manual run on staging with a real WhatsApp number | staging | none | pilot sign-off |

## Rules
* Each test's docstring names the requirement ids it proves; the traceability matrix links back.
* Time is controlled through `FixedClock`; no sleeps.
* Each integration test onboards its own clinic(s) with random phone/slug → tests are order-independent and parallel-safe.
* The test DB is migrated `downgrade base → upgrade head` once per session (exercises both directions).
* Integration tests are **skipped with a reason** when the DB is unreachable locally; CI fails if anything is skipped.

## Smoke test
`scripts/smoke_e2e.py <base-url> <server-log>` drives a running dev server end-to-end (dev OTP read from the log).

## Commands
```bash
docker compose up -d db redis
rtk pytest apps/api/tests -q -m "not integration"
rtk pytest apps/api/tests -q -rs
```
(on Windows put `.venv/Scripts` first on `PATH` so `rtk pytest` uses the project interpreter.)
