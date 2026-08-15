#!/usr/bin/env bash
set -euo pipefail

: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${APP_DB_AUDIT_USER:?APP_DB_AUDIT_USER is required}"
: "${APP_DB_AUDIT_PASSWORD:?APP_DB_AUDIT_PASSWORD is required}"

case "$APP_DB_AUDIT_USER" in
  (*[!a-zA-Z0-9_]*|'')
    echo "APP_DB_AUDIT_USER must contain only letters, numbers, and underscores" >&2
    exit 1
    ;;
esac

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=audit_user="$APP_DB_AUDIT_USER" \
  --set=audit_password="$APP_DB_AUDIT_PASSWORD" \
  --set=database_name="$POSTGRES_DB" <<'SQL'
CREATE ROLE :"audit_user" LOGIN PASSWORD :'audit_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
REVOKE ALL ON DATABASE :"database_name" FROM :"audit_user";
REVOKE ALL ON SCHEMA commerce FROM :"audit_user";
REVOKE ALL ON SCHEMA public FROM :"audit_user";
REVOKE ALL ON SCHEMA text_to_sql_audit FROM :"audit_user";
GRANT CONNECT ON DATABASE :"database_name" TO :"audit_user";
GRANT USAGE ON SCHEMA text_to_sql_audit TO :"audit_user";
GRANT SELECT, INSERT, UPDATE ON TABLE
  text_to_sql_audit.query_audit_records,
  text_to_sql_audit.query_feedback
TO :"audit_user";
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA text_to_sql_audit TO :"audit_user";
SQL
