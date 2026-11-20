---
name: testing-and-qa
description: Test strategy — unit, integration on real Postgres/Redis, concurrency, security, assistant fixtures, E2E and acceptance mapping. Use when writing or running tests.
---
# Testing and QA
**Purpose** Tests that prove business rules, traced to requirement ids.
**When to use** Every change.
**Required context** `docs/testing-strategy.md`, `docs/requirements-traceability.md`.

## Engineering rules
- Each test docstring lists the ids it proves (`"""BR-1, AC-2"""`); update matrix status when it passes.
- Pure policies: table-driven unit tests, no DB.
- Services/APIs: integration tests on real Postgres (`docker compose up -d db redis`) connecting as the runtime role; each test creates its own clinic.
- Concurrency: `asyncio.gather` over separate sessions; assert exactly one winner.
- Mock only provider boundaries (Fake WhatsApp / LLM / Exotel). Never mock the DB or our services in integration tests.
- Control time through the injected `Clock`; never `sleep`.
- Iterate with `rtk pytest -q -m "not integration"`; run the full suite at milestones. Report real counts only.

## Validation checklist
- [ ] Every P0 FR/BR touched has a test id in the matrix
- [ ] Bugs get a failing test first
