---
name: system-architecture
description: ClinicDesk module boundaries, dependency rules and ADRs. Use when adding a module, moving code between modules, or making a cross-cutting design decision.
---
# System architecture
**Purpose** Keep the modular monolith coherent.
**When to use** New module/file placement, cross-module calls, new infra dependency, any decision worth an ADR.
**Required context** `docs/architecture/system-design.md` §2, `docs/decisions/`.

## Engineering rules
- Layout per module: `models.py`, `schemas.py`, `service.py`, `router.py`, optional pure `policy.py`.
- `router → service → models/policy`; routers hold no business logic.
- `policy.py` is pure: no I/O, `now` passed in. All BR-* logic lives in policies.
- `core/` imports no module. `assistant` acts only through `assistant/tools.py`.
- Providers sit behind protocols in `integrations/`; fakes are never selectable in production.
- Cross-module side effects: same transaction, or `scheduled_jobs` / `outbox_messages` rows. No in-memory event bus.
- New dependency or infra component → ADR with reason and rejected alternatives.

## Workflow
1. Locate the owning module in the traceability matrix. 2. Put pure rules in `policy.py`, orchestration in `service.py`. 3. Record irreversible decisions as `docs/decisions/NNNN-*.md`.

## Validation checklist
- [ ] No import of another module's `models` except through its service
- [ ] New rule has a pure policy + unit test referencing the BR/FR id
- [ ] ADR written for irreversible decisions; system-design updated
