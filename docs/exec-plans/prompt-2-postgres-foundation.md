# ExecPlan: Prompt 2 PostgreSQL Foundation

## Goal

Add a local PostgreSQL 16 database with a deterministic e-commerce analytics schema and seed data for later Text-to-SQL work.

## Non-goals

- Do not connect FastAPI to PostgreSQL.
- Do not add SQLAlchemy, database drivers, LLM providers, frontend code, or application query execution.
- Do not add production credentials or destructive scripts under `database/`.

## Current context

The repository has a FastAPI health-check foundation and an intended architecture where generated SQL eventually runs through a read-only PostgreSQL role. There is no existing Docker Compose file or PostgreSQL initialization.

## Implementation path

1. Add `docker-compose.yml` with PostgreSQL 16, a named volume, safe local defaults, environment-variable overrides, and a healthcheck.
2. Add ordered initialization files under `database/init/`:
   - `00_schema.sql` for schema, tables, constraints, and indexes.
   - `10_seed.sql` for deterministic seed records.
   - `20_readonly_role.sh` for the future generated-SQL read-only role and grants.
3. Add `scripts/database-smoke-test.sh` to validate expected tables, representative row counts, deterministic analytical edge cases, and read-only role behavior.
4. Add `database/README.md` with startup, reset, inspection, and smoke-test commands.
5. Add Makefile database targets for consistent local commands.
6. Update `.env.example` with database variable names only.

## Safety and rollback

The database uses a local named Docker volume and synthetic seed data only. Resetting the database requires an explicit `docker compose down --volumes --remove-orphans`. Rollback is removing the added Compose, init, script, README, and Makefile/env changes.

## Validation

- `docker compose config`
- `make db-up`
- `make db-smoke`
- `make db-reset`
- `make db-smoke`
- `make db-down`
- `git diff --check`

Expected outcome: Compose validates, PostgreSQL becomes healthy, initialization succeeds on a fresh volume, the smoke test passes, and SQL seed data remains deterministic across resets.

## Completion criteria

The repository has a realistic local PostgreSQL schema and deterministic seed data with read-only role grants ready for later connectivity work, while FastAPI remains unconnected.
