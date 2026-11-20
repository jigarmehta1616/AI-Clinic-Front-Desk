---
name: frontend-engineering
description: React + TypeScript + Vite + Tailwind + TanStack Query conventions for the apps/web dashboard and TV display. Use for any UI work.
---
# Frontend engineering
**Purpose** A fast, calm dashboard a receptionist can use untrained in 10 minutes (NFR-7).
**When to use** Anything in `apps/web`.
**Required context** `apps/web/src/`, OpenAPI at `/api/v1/openapi.json`.

## Engineering rules
- Server state only via TanStack Query; keys `[clinicId, resource, params]`; invalidate on WebSocket events.
- Types generated from OpenAPI; no `any`.
- Access token in memory; refresh via HttpOnly cookie endpoint; on 401 refresh once, then sign out.
- Top actions (book, reschedule, cancel, mark arrived, issue token, call next) ≤ 2 clicks from Today.
- Every view has loading, empty, error-with-retry and success states. No dead buttons.
- Accessible: semantic HTML, labels, visible focus, 4.5:1 contrast, 44 px touch targets.
- Responsive at 360 / 768 / 1280 px. TV route is chromeless with large type.
- Never render patient PII on public/TV/QR routes.

## Validation checklist
- [ ] `npm run typecheck && npm run lint && npm test`
- [ ] Checked in a browser at three widths
