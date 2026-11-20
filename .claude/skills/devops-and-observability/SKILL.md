---
name: devops-and-observability
description: Docker Compose, Nginx, GitHub Actions CI, AWS Mumbai deployment, logging, Sentry, Langfuse, backups and incident response. Use for infra, CI or ops work.
---
# DevOps and observability
**Purpose** Boring, observable, recoverable operations.
**When to use** `docker-compose.yml`, `infrastructure/`, `.github/workflows/`, `docs/deployment.md`, `docs/runbooks/`.

## Engineering rules
- Images pinned by version; non-root user; healthchecks on every service.
- Config only via env; `.env.example` is the contract. Fakes refused when `ENV=production`.
- CI: ruff, mypy, unit + integration tests (Postgres/Redis services), web typecheck/lint/test, docker build.
- JSON logs to stdout with `request_id`, `clinic_id`, masked phone. Sentry with PII scrubbing. Langfuse for AI traces.
- Backups: daily + 7-day PITR in ap-south-1; monthly restore drill recorded in `docs/runbooks/backup-restore.md`.
- No production deploy without explicit human approval.

## Validation checklist
- [ ] `docker compose config` valid
- [ ] Runbook updated for new failure modes
