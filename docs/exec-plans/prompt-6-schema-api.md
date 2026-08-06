# ExecPlan: Prompt 6 Enriched Schema API

## Goal

Expose `GET /v1/schema` with typed response models, process-local caching, explicit refresh, safe categorical samples, direct relationship metadata, and bundled business glossary definitions.

## Non-goals

- Do not add query generation, SQL validation, or SQL execution behavior.
- Do not expose unrestricted data samples.
- Do not expose database credentials or raw database errors.

## Current context

Prompt 5 added pure schema domain models and `SchemaIntrospectionService`. The current seeded database has eight business tables under `commerce`, including sensitive identifiers such as customer emails, names, provider payment IDs, external refund IDs, order/shipment numbers, tracking numbers, and SKUs.

## Implementation path

1. Add business glossary domain models and a bundled YAML glossary resource.
2. Add a strict glossary loader for the known resource format.
3. Add `SchemaSampleService` for bounded distinct samples from explicitly configured non-sensitive text columns.
4. Add `SchemaCatalogService` to coordinate introspection, samples, glossary loading, and in-memory TTL caching.
5. Add FastAPI response models and `GET /v1/schema` under `backend/app/api`.
6. Register the schema router in app creation without changing `/health`.
7. Add unit tests for glossary loading, sampling safety, caching/refresh, and endpoint response translation.
8. Add Docker-backed integration tests for the endpoint against seeded PostgreSQL.
9. Document endpoint behavior in `docs/SCHEMA_API.md`.

## Safety and rollback

Sampling is read-only, low-cardinality, explicitly allowlisted, timeout-bounded, and protected by a sensitive-column denylist. Rollback is removing the new API, catalog, sampling, glossary resource, tests, and documentation.

## Validation

- `make backend-lint`
- `make backend-typecheck`
- `make backend-test`
- `TEXT_TO_SQL_DATABASE_PORT=55432 make backend-integration-test`
- `TEXT_TO_SQL_DATABASE_PORT=55432 make backend-check-integration`

Expected outcome: all checks pass, `/v1/schema` returns schema metadata with safe samples and glossary metadata, and sensitive columns have empty `sample_values`.

## Completion criteria

`GET /v1/schema` returns deterministic tables, columns, relationships, safe sample values, glossary metadata, and cache metadata. Refresh bypasses the cache, sensitive columns are not sampled, and unit/integration/lint/type checks pass.
