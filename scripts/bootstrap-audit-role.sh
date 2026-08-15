#!/usr/bin/env bash
set -euo pipefail

service_name="${POSTGRES_SERVICE:-postgres}"
database_name="${POSTGRES_DB:-text_to_sql}"
owner_user="${POSTGRES_USER:-text_to_sql_owner}"
audit_user="${APP_DB_AUDIT_USER:-text_to_sql_audit_writer}"
audit_password="${APP_DB_AUDIT_PASSWORD:-text_to_sql_audit_writer_local_password}"

case "$audit_user" in
  (*[!a-zA-Z0-9_]*|'')
    echo "APP_DB_AUDIT_USER must contain only letters, numbers, and underscores" >&2
    exit 1
    ;;
esac

role_exists="$(
  docker compose exec -T "$service_name" psql --username "$owner_user" --dbname "$database_name" \
    --tuples-only --no-align --command "SELECT 1 FROM pg_roles WHERE rolname = '$audit_user';"
)"

if [ "$role_exists" != "1" ]; then
  docker compose exec -T "$service_name" psql -v ON_ERROR_STOP=1 \
    --username "$owner_user" --dbname "$database_name" \
    --set=audit_user="$audit_user" --set=audit_password="$audit_password" <<'SQL'
CREATE ROLE :"audit_user" LOGIN PASSWORD :'audit_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
SQL
fi

docker compose exec -T "$service_name" psql -v ON_ERROR_STOP=1 \
  --username "$owner_user" --dbname "$database_name" \
  --set=audit_user="$audit_user" --set=database_name="$database_name" <<'SQL'
REVOKE ALL ON DATABASE :"database_name" FROM :"audit_user";
REVOKE ALL ON SCHEMA commerce FROM :"audit_user";
REVOKE ALL ON SCHEMA public FROM :"audit_user";
REVOKE ALL ON SCHEMA text_to_sql_audit FROM :"audit_user";
GRANT CONNECT ON DATABASE :"database_name" TO :"audit_user";
GRANT USAGE ON SCHEMA text_to_sql_audit TO :"audit_user";
GRANT SELECT, INSERT, UPDATE ON TABLE text_to_sql_audit.query_audit_records, text_to_sql_audit.query_feedback TO :"audit_user";
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA text_to_sql_audit TO :"audit_user";
SQL
