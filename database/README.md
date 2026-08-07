# Database

This directory contains the local PostgreSQL foundation for the Text-to-SQL project. The schema and seed data are synthetic, deterministic, and intended for analytics-style joins, aggregations, date filters, revenue questions, refunds, and shipment timing questions.

## Startup

Copy `.env.example` to `.env` if you want to override local defaults. Keep `.env` untracked.

```sh
docker compose up -d postgres
docker compose ps
```

The Compose service uses PostgreSQL 16 and mounts `database/init/` into the standard first-run initialization directory. Init files run only when the named Docker volume is fresh.

## Smoke test

```sh
./scripts/database-smoke-test.sh
```

The smoke test checks expected tables, representative row counts, reconciliation queries, required edge cases, and that the read-only role cannot write.

## Inspect

```sh
docker compose exec postgres psql -U "${POSTGRES_USER:-text_to_sql_owner}" -d "${POSTGRES_DB:-text_to_sql}"
```

Useful SQL:

```sql
\dt commerce.*
SELECT status, count(*) FROM commerce.orders GROUP BY status ORDER BY status;
SELECT * FROM commerce.shipments WHERE delivered_at IS NULL;
```

## Reset

Resetting removes the local PostgreSQL volume and reruns initialization from scratch.

```sh
docker compose down --volumes --remove-orphans
docker compose up -d postgres
./scripts/database-smoke-test.sh
```
