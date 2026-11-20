"""Helpers for tenant RLS in migrations (ADR-0002). Import from revisions as `from rls import ...`."""

APP_ROLE = "clinicdesk_app"

FUNCTIONS_SQL = """
CREATE OR REPLACE FUNCTION app_clinic_id() RETURNS uuid LANGUAGE sql STABLE AS
$$ SELECT NULLIF(current_setting('app.clinic_id', true), '')::uuid $$;
CREATE OR REPLACE FUNCTION app_user_id() RETURNS uuid LANGUAGE sql STABLE AS
$$ SELECT NULLIF(current_setting('app.user_id', true), '')::uuid $$;
CREATE OR REPLACE FUNCTION app_bypass_rls() RETURNS boolean LANGUAGE sql STABLE AS
$$ SELECT coalesce(current_setting('app.bypass_rls', true), 'off') = 'on' $$;
"""

DROP_FUNCTIONS_SQL = """
DROP FUNCTION IF EXISTS app_clinic_id(); DROP FUNCTION IF EXISTS app_user_id(); DROP FUNCTION IF EXISTS app_bypass_rls();
"""


def enable_rls_sql(table: str, using: str | None = None, check: str | None = None) -> str:
    using = using or "clinic_id = app_clinic_id() OR app_bypass_rls()"
    check = check or using
    return (
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;\n"
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;\n"
        f"CREATE POLICY tenant_isolation ON {table} USING ({using}) WITH CHECK ({check});\n"
    )


def grant_dml_sql(table: str, *, append_only: bool = False) -> str:
    privs = "SELECT, INSERT" if append_only else "SELECT, INSERT, UPDATE, DELETE"
    return f"GRANT {privs} ON {table} TO {APP_ROLE};\n"
