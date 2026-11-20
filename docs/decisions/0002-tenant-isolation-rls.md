# ADR-0002 Tenant isolation: scoped queries + Postgres RLS
Status: accepted
**Context** DP-6/AC-10 require proof that one clinic cannot read another's data. App-level filtering alone fails on a single forgotten `WHERE`.
**Decision** (1) Tenant id comes only from the verified JWT and is held in a request-scoped `TenantContext`; services always filter by it. (2) Every tenant table has `FORCE ROW LEVEL SECURITY` with a policy on `current_setting('app.clinic_id')`, set transaction-locally (`set_config(...,true)`) at session start. Runtime DB role is not table owner and has no BYPASSRLS. Platform jobs that legitimately span tenants set `app.bypass_rls=on` explicitly in a dedicated code path that is audited.
**Consequences** Must set context inside every transaction (enforced by the session factory); tests run as the runtime role to prove policies.
