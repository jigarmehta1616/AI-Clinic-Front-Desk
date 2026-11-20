---
name: security-and-privacy
description: RBAC, tenant isolation, auth tokens, DPDP-driven controls (consent, DSR, retention, breach), encryption, secrets and LLM data minimisation. Use for any change touching auth, PII or access control.
---
# Security and privacy
**Purpose** Protect patient data; make isolation provable.
**When to use** Auth, RBAC, PII fields, consent, logging, admin access, LLM inputs.
**Required context** `docs/architecture/security-model.md`, ADR-0002, ADR-0007, DP-1..DP-10.

## Engineering rules
- Tenant from token only; a scoped lookup miss on a tenant route → 403 + `access_denied` audit row (AC-10).
- New permission → RBAC matrix + per-role tests.
- Consent is append-only `consent_events`; booking consent ≠ reminder/recall consent (DP-2).
- Store only FRD §7 fields; never diagnoses, prescriptions, reports or card data.
- Mask phones in logs; never put PII in URLs or query strings.
- Secrets only from env / AWS SSM; add placeholders to `.env.example`.
- Never write "DPDP compliant"; write "implements FRD DP-x (legal review pending)".
- Platform admins read conversations only with an active `support_access_grants` row (DP-10).

## Validation checklist
- [ ] Cross-tenant and role-denial tests
- [ ] No PII in log output
- [ ] Built-in `security-review` run on auth changes
