#!/usr/bin/env bash
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --tuples-only --no-align --command "
    SELECT 1
    WHERE to_regclass('commerce.orders') IS NOT NULL
      AND to_regclass('text_to_sql_audit.query_audit_records') IS NOT NULL
      AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$APP_DB_READONLY_USER')
      AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$APP_DB_AUDIT_USER');
  " | grep -qx '1'
