# ClinicDesk AI

WhatsApp-first AI front desk for dental and physiotherapy clinics in Gujarat: booking, live token queue, reminders, recall and recovered-revenue reporting. Multi-tenant SaaS, Python/FastAPI + PostgreSQL + React.

**Status:** pre-pilot — M1–M6 done (backend, dashboard, missed calls, platform admin, production images); not deployed. See [`docs/project-status.md`](docs/project-status.md).

## Quick start (Windows dev box; Linux/macOS: use `.venv/bin`)
```bash
cp .env.example .env            # then replace every value
docker compose up -d db redis   # Postgres on 5433, Redis on 6380
python -m venv .venv && .venv/Scripts/python -m pip install -e "apps/api[dev]"
.venv/Scripts/python -m alembic -c apps/api/alembic.ini upgrade head
.venv/Scripts/python -m uvicorn clinicdesk.main:create_app --factory --app-dir apps/api/src --reload
```
Worker (jobs, reminders, WhatsApp dispatch): `.venv/Scripts/arq clinicdesk.worker.WorkerSettings`

Dashboard (proxies /api and /api/v1/ws to :8000):
```bash
npm --prefix apps/web install
npm --prefix apps/web run dev    # http://localhost:5173
```
Demo data (dev only; OTP codes are printed in the API log): `.venv/Scripts/python scripts/seed_demo.py http://127.0.0.1:8000 <api-log-file>`, then sign in as +91 90000 00001.

Tests: `.venv/Scripts/python -m pytest apps/api/tests -q -rs` · `npm --prefix apps/web test`

After API changes: `.venv/Scripts/python scripts/export_openapi.py && npm --prefix apps/web run gen:api` (CI fails if they drift).

Production stack (local trial with your own cert): see [`docs/deployment.md`](docs/deployment.md).

## Docs
* Requirements → [`docs/requirements-traceability.md`](docs/requirements-traceability.md) (FRD in `docs/source/`)
* Architecture → [`docs/architecture/`](docs/architecture/) · decisions → [`docs/decisions/`](docs/decisions/)
* API → [`docs/api/README.md`](docs/api/README.md) · testing → [`docs/testing-strategy.md`](docs/testing-strategy.md) · deployment → [`docs/deployment.md`](docs/deployment.md)

Compliance note: the product implements the FRD's DPDP-driven requirements (DP-1..DP-10); legal compliance has **not** been reviewed.
