#!/usr/bin/env bash
set -euo pipefail

service_name="${POSTGRES_SERVICE:-postgres}"
database_name="${POSTGRES_DB:-text_to_sql}"
owner_user="${POSTGRES_USER:-text_to_sql_owner}"
readonly_user="${APP_DB_READONLY_USER:-text_to_sql_reader}"
readonly_password="${APP_DB_READONLY_PASSWORD:-text_to_sql_reader_local_password}"

case "$readonly_user" in
  (*[!a-zA-Z0-9_]*|'')
    echo "APP_DB_READONLY_USER must contain only letters, numbers, and underscores" >&2
    exit 1
    ;;
esac

compose() {
  docker compose "$@"
}

psql_owner() {
  compose exec -T "$service_name" psql \
    -v ON_ERROR_STOP=1 \
    --username "$owner_user" \
    --dbname "$database_name" \
    "$@"
}

role_exists="$(
  psql_owner --tuples-only --no-align \
    --command "SELECT 1 FROM pg_roles WHERE rolname = '$readonly_user';"
)"

if [ "$role_exists" != "1" ]; then
  psql_owner \
    --set=readonly_user="$readonly_user" \
    --set=readonly_password="$readonly_password" <<'SQL'
CREATE ROLE :"readonly_user" LOGIN PASSWORD :'readonly_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
SQL
fi

psql_owner \
  --set=readonly_user="$readonly_user" \
  --set=database_name="$database_name" <<'SQL'
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON DATABASE :"database_name" FROM PUBLIC;
REVOKE TEMPORARY ON DATABASE :"database_name" FROM PUBLIC;
REVOKE ALL ON DATABASE :"database_name" FROM :"readonly_user";
REVOKE ALL ON SCHEMA public FROM :"readonly_user";
REVOKE ALL ON SCHEMA commerce FROM :"readonly_user";
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA commerce FROM :"readonly_user";
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA commerce FROM :"readonly_user";
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

echo "Read-only application role bootstrapped."
