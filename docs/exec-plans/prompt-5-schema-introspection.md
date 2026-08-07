# ExecPlan: Prompt 5 Schema Introspection

## Goal

Add automatic PostgreSQL schema introspection using SQLAlchemy Inspector. The service should return typed domain models for database schemas, tables, columns, primary keys, and foreign keys, including deterministic machine-readable metadata and a display-friendly direct relationship path.

## Non-goals

- Do not add a FastAPI endpoint or response models.
- Do not retrieve sample values or categorical metadata.
- Do not change PostgreSQL schema, seed data, privileges, SQL generation, query validation, or execution behavior.

## Current context

The backend currently has FastAPI health checks, SQLAlchemy engine creation, and Docker-backed PostgreSQL seed data under the `commerce` schema. The architecture reserves `backend/app/domain` for schema models and `backend/app/services` for orchestration, but those packages have not yet had behavior.

The seeded schema has eight business tables. Introspection needs to handle the non-default `commerce` schema, a self-referencing `categories.parent_category_id` relationship, and multi-hop relationship chains that will later be useful to Prompt 6 and query planning.

## Implementation path

1. Add pure domain models under `backend/app/domain/schema.py`.
2. Add `SchemaIntrospectionService` under `backend/app/services/schema_introspection.py`.
3. Add settings for configured schema allowlisting, defaulting to `commerce`.
4. Filter PostgreSQL internal schemas and project audit-table naming patterns before introspecting table details.
5. Use SQLAlchemy `inspect(engine)` by default while accepting an injected Inspector-like object for unit tests.
6. Preserve Inspector column order, sort schemas and tables alphabetically, and sort foreign keys by constrained columns, referred table, referred columns, and name.
7. Add unit tests with mocked Inspector responses for ordering, filtering, column metadata, primary keys, and foreign-key display paths.
8. Add Docker-backed integration coverage against the seeded PostgreSQL database.
9. Keep `docs/STATUS.md` unchanged because this is not a phase boundary.

## Safety and rollback

The implementation is read-only metadata inspection through the existing SQLAlchemy engine and read-only database role. Rollback is removing the new domain/service modules, tests, settings field, and this plan.

## Validation

- `make backend-lint`
- `make backend-typecheck`
- `make backend-test`
- `make db-up`
- `make backend-integration-test`
- `make backend-check-integration`

Expected outcome: unit tests pass without Docker, integration tests pass against the seeded PostgreSQL database, and lint/type checks are clean.

## Completion criteria

The service accurately represents all seeded business tables, includes column types/nullability/defaults, primary keys, and direct foreign-key relationships, excludes configured internal/audit objects, remains independent from FastAPI response contracts, and has passing unit, integration, lint, and type checks.
