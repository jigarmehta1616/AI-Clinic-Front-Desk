---
name: code-review
description: ClinicDesk review checklist for correctness, tenant isolation, business rules, security, tests and docs before a change is considered done. Use before committing a milestone.
---
# Code review
**Purpose** Catch regressions before they reach a clinic.
**When to use** Before every milestone commit. Also run the built-in `security-review` for auth/PII changes.
**Required context** The diff (`rtk git diff`), traceability matrix.

## Checklist
- **Correctness**: BR-* enforced in policy and, where possible, a DB constraint; boundary cases (IST midnight, session end, 21:00/08:00, 24 h window edge).
- **Concurrency/idempotency**: double-click, duplicate webhook, duplicate job, two workers.
- **Tenancy**: every query scoped; RLS on new tables; cross-tenant test.
- **Security**: permission on route, input validation, no PII in logs/URLs, no secrets committed.
- **Failure modes**: provider down, timeout, Redis down → degrade without data loss.
- **Tests**: requirement ids, real DB for services, actually executed, counts reported.
- **Docs**: matrix, `docs/project-status.md`, ADR if a decision was made.
- **Hygiene**: no dead code, no unexplained TODOs, no unrelated changes.
