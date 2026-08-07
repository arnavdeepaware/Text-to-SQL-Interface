#!/usr/bin/env bash
set -euo pipefail

service_name="${POSTGRES_SERVICE:-postgres}"
database_name="${POSTGRES_DB:-text_to_sql}"
owner_user="${POSTGRES_USER:-text_to_sql_owner}"
readonly_user="${APP_DB_READONLY_USER:-text_to_sql_reader}"

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

scalar() {
  psql_owner --tuples-only --no-align --command "$1"
}

assert_eq() {
  actual="$1"
  expected="$2"
  label="$3"

  if [ "$actual" != "$expected" ]; then
    echo "FAIL: $label expected $expected, got $actual" >&2
    exit 1
  fi

  echo "OK: $label = $actual"
}

echo "Checking PostgreSQL health..."
compose exec -T "$service_name" pg_isready --username "$owner_user" --dbname "$database_name"

echo "Checking tables..."
table_count="$(
  scalar "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'commerce' AND table_name IN ('customers', 'categories', 'products', 'orders', 'order_items', 'payments', 'refunds', 'shipments');"
)"
assert_eq "$table_count" "8" "commerce table count"

assert_eq "$(scalar 'SELECT count(*) FROM commerce.customers;')" "6" "customers"
assert_eq "$(scalar 'SELECT count(*) FROM commerce.categories;')" "5" "categories"
assert_eq "$(scalar 'SELECT count(*) FROM commerce.products;')" "8" "products"
assert_eq "$(scalar 'SELECT count(*) FROM commerce.orders;')" "9" "orders"
assert_eq "$(scalar 'SELECT count(*) FROM commerce.order_items;')" "14" "order_items"
assert_eq "$(scalar 'SELECT count(*) FROM commerce.payments;')" "10" "payments"
assert_eq "$(scalar 'SELECT count(*) FROM commerce.refunds;')" "2" "refunds"
assert_eq "$(scalar 'SELECT count(*) FROM commerce.shipments;')" "7" "shipments"

echo "Checking representative analytical invariants..."
assert_eq "$(
  scalar "SELECT count(*) FROM commerce.orders o LEFT JOIN (SELECT order_id, sum(line_total_cents) AS item_total FROM commerce.order_items GROUP BY order_id) i USING (order_id) WHERE o.subtotal_cents <> i.item_total;"
)" "0" "orders with mismatched item subtotal"

assert_eq "$(
  scalar "SELECT count(*) FROM commerce.orders WHERE total_cents <> subtotal_cents - discount_cents + tax_cents + shipping_cents;"
)" "0" "orders with mismatched total"

assert_eq "$(
  scalar "SELECT count(*) FROM (SELECT p.payment_id FROM commerce.payments p JOIN commerce.refunds r USING (payment_id) GROUP BY p.payment_id, p.amount_cents HAVING sum(r.amount_cents) > p.amount_cents) over_refunded;"
)" "0" "over-refunded payments"

assert_eq "$(scalar "SELECT count(*) FROM commerce.orders WHERE status = 'cancelled';")" "2" "cancelled orders"
assert_eq "$(scalar "SELECT count(*) FROM commerce.refunds WHERE amount_cents < (SELECT amount_cents FROM commerce.payments WHERE payments.payment_id = refunds.payment_id);")" "1" "partial refunds"
assert_eq "$(scalar 'SELECT count(*) FROM commerce.shipments WHERE delivered_at IS NULL;')" "2" "shipments with NULL delivered_at"
assert_eq "$(
  scalar "SELECT count(*) FROM commerce.products p WHERE NOT EXISTS (SELECT 1 FROM commerce.order_items oi JOIN commerce.orders o USING (order_id) WHERE oi.product_id = p.product_id AND o.ordered_at >= '2026-01-01 00:00:00+00');"
)" "1" "products without recent orders"

echo "Checking read-only role cannot write..."
set +e
compose exec -T "$service_name" psql \
  -v ON_ERROR_STOP=1 \
  --username "$readonly_user" \
  --dbname "$database_name" \
  --command "INSERT INTO commerce.categories (name) VALUES ('Forbidden Write');" >/dev/null 2>&1
readonly_insert_status="$?"
set -e

if [ "$readonly_insert_status" -eq 0 ]; then
  echo "FAIL: read-only role unexpectedly inserted a row" >&2
  exit 1
fi

echo "OK: read-only role insert denied"
echo "Database smoke test passed."
