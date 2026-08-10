#!/usr/bin/env bash
set -euo pipefail

: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${APP_DB_READONLY_USER:?APP_DB_READONLY_USER is required}"
: "${APP_DB_READONLY_PASSWORD:?APP_DB_READONLY_PASSWORD is required}"

case "$APP_DB_READONLY_USER" in
  (*[!a-zA-Z0-9_]*|'')
    echo "APP_DB_READONLY_USER must contain only letters, numbers, and underscores" >&2
    exit 1
    ;;
esac

role_exists="$(
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    --tuples-only --no-align \
    --command "SELECT 1 FROM pg_roles WHERE rolname = '$APP_DB_READONLY_USER';"
)"

if [ "$role_exists" != "1" ]; then
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    --set=readonly_user="$APP_DB_READONLY_USER" \
    --set=readonly_password="$APP_DB_READONLY_PASSWORD" <<'SQL'
CREATE ROLE :"readonly_user" LOGIN PASSWORD :'readonly_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
SQL
fi

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=readonly_user="$APP_DB_READONLY_USER" \
  --set=database_name="$POSTGRES_DB" <<'SQL'
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON DATABASE :"database_name" FROM PUBLIC;
REVOKE TEMPORARY ON DATABASE :"database_name" FROM PUBLIC;
REVOKE ALL ON DATABASE :"database_name" FROM :"readonly_user";
REVOKE ALL ON SCHEMA public FROM :"readonly_user";
REVOKE ALL ON SCHEMA commerce FROM :"readonly_user";
REVOKE ALL ON SCHEMA text_to_sql_audit FROM :"readonly_user";
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA commerce FROM :"readonly_user";
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA commerce FROM :"readonly_user";
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA text_to_sql_audit FROM :"readonly_user";
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA text_to_sql_audit FROM :"readonly_user";
GRANT CONNECT ON DATABASE :"database_name" TO :"readonly_user";
GRANT USAGE ON SCHEMA commerce TO :"readonly_user";
GRANT SELECT ON TABLE
  commerce.categories,
  commerce.customers,
  commerce.order_items,
  commerce.orders,
  commerce.payments,
  commerce.products,
  commerce.refunds,
  commerce.shipments
TO :"readonly_user";
ALTER ROLE :"readonly_user" WITH
  LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
ALTER ROLE :"readonly_user" SET search_path = commerce, pg_catalog;
ALTER ROLE :"readonly_user" SET default_transaction_read_only = on;
SQL
