#!/bin/sh
# Creates the schema-owner role, the RLS-subject runtime role, and dev + test databases.
# Runs once on first container start (docker-entrypoint-initdb.d).
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" \
  -v owner_pw="$DB_OWNER_PASSWORD" -v app_pw="$DB_APP_PASSWORD" <<'SQL'
CREATE ROLE clinicdesk_owner LOGIN PASSWORD :'owner_pw';
CREATE ROLE clinicdesk_app LOGIN PASSWORD :'app_pw' NOSUPERUSER NOBYPASSRLS;
CREATE DATABASE clinicdesk OWNER clinicdesk_owner;
CREATE DATABASE clinicdesk_test OWNER clinicdesk_owner;
SQL
for db in clinicdesk clinicdesk_test; do
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" -d "$db" <<'SQL'
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT ALL ON SCHEMA public TO clinicdesk_owner;
GRANT USAGE ON SCHEMA public TO clinicdesk_app;
SQL
done
