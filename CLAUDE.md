# ClinicDesk AI — project rules

WhatsApp-first AI front desk (booking, token queue, reminders, recall, revenue recovery) for dental & physio clinics in Gujarat. Multi-tenant SaaS. Spec: `docs/source/FRD.docx` → requirements in `docs/requirements-traceability.md` (keep IDs: FR-x.y, BR-n, DP-n, NFR-n, AC-n).

## Where things are
- `apps/api` — Python package `clinicdesk` (FastAPI api + ARQ worker entrypoints), Alembic migrations, tests.
- `apps/web` — React + TS + Vite + Tailwind + TanStack Query dashboard.
- `docs/architecture/*` design · `docs/decisions/*` ADRs · `docs/project-status.md` **current progress + next action (read first, update at each milestone)**.
- `infrastructure/` docker + nginx · `docker-compose.yml` local Postgres (5433) + Redis (6380).

## Non-negotiables
1. Tenant id only from the verified token; every tenant table has `clinic_id` + forced RLS (ADR-0002).
2. Business rules are pure functions in `modules/*/policy.py` with `now` injected; DB constraints back them (BR-1 partial unique index).
3. Every booking/cancel/status change writes `audit_log` in the same transaction (BR-13).
4. External events and jobs are idempotent (unique keys) and durable in Postgres (ADR-0004).
5. LLM only extracts intent/entities; deterministic tools act (ADR-0006). Never medical advice (BR-10).
6. No secrets in git; no fakes in production; never claim tests passed unless run; never claim legal compliance.
7. Ask before destructive operations or any deploy.

## Commands (run from repo root; RTK prefix keeps output small)
```bash
docker compose up -d db redis
.venv/Scripts/python -m alembic -c apps/api/alembic.ini upgrade head   # venv at repo root (Linux/CI: .venv/bin/python)
rtk pytest apps/api/tests -q -m "not integration"   # fast loop
rtk pytest apps/api/tests -q                        # full (needs db)
rtk ruff check apps/api
```
RTK (rtk-ai/rtk 0.48) is installed with the Claude hook; prefer `rtk git …`, `rtk grep`, `rtk pytest`. Check savings with `rtk gain`.

## Skills (`.claude/skills/`) — load only what the task needs
system-architecture · backend-engineering · database-engineering · ai-agent-engineering · whatsapp-integration · scheduling-and-queue · recall-and-revenue · frontend-engineering · security-and-privacy · testing-and-qa · devops-and-observability · code-review

## Working loop
Read `docs/project-status.md` → pick next task → relevant skill → smallest complete change → targeted tests → review diff (code-review skill) → update matrix + status → commit.
