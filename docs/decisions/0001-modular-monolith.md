# ADR-0001 Modular monolith, one Python package, two process types
Status: accepted (2026-11-20)
**Context** 5-clinic pilot, ~0.25 msg/s average load (NFR-6), small team, 6-week P0 timeline.
**Decision** One package `clinicdesk` (in `apps/api`) with `api` (uvicorn) and `worker` (ARQ) entrypoints. `apps/worker` from the suggested layout is not created: a separate package would duplicate models/services. Modules have explicit boundaries (system-design §2).
**Consequences** Single deploy unit and migration history. If a module needs independent scaling later, its boundary is already explicit.
