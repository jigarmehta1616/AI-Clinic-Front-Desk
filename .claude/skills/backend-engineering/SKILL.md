---
name: backend-engineering
description: FastAPI/Pydantic/service conventions for apps/api — routers, validation, errors, transactions. Use when writing or changing API endpoints or services.
---
# Backend engineering
**Purpose** Consistent, safe API and service code.
**When to use** Any endpoint, schema or service change in `apps/api`.
**Required context** `apps/api/src/clinicdesk/core/`, the module you touch, `docs/requirements-traceability.md`.

## Engineering rules
- Routes under `/api/v1`. Request models are Pydantic with `extra="forbid"`; never return ORM objects.
- Tenant and actor come from `Depends(get_ctx)` (verified JWT), never from path/body.
- Every route declares `Depends(require(Permission.X))`.
- Services own the transaction; one business operation = one transaction including audit, jobs and outbox rows.
- Domain errors subclass `core.errors.DomainError` with a stable `code`; handler maps to HTTP (`SlotTaken`→409, `PolicyViolation`→422, `Forbidden`→403, `NotFound`→404).
- Inject `Clock`; never call `datetime.now()` inside services or policies.
- structlog only; mask phones; never log message bodies at INFO.

## Workflow
Schema → policy (pure) → service (txn) → router → integration test → update `docs/api/` and matrix.

## Validation checklist
- [ ] Permission + tenant scoping present
- [ ] Audit row for state changes (BR-13)
- [ ] Integration test hits the real DB
