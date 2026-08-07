# Schema API

`GET /v1/schema` returns a safe, enriched view of the configured PostgreSQL business schemas for schema-aware clients.

## Request

- `GET /v1/schema`
- `GET /v1/schema?refresh=true`

The optional `refresh=true` query parameter bypasses the in-memory process cache and replaces it after a successful rebuild.

## Response

The response includes:

- `schemas`: configured exposed schema names.
- `tables`: table metadata with columns, SQL types, nullability, defaults, primary keys, direct foreign keys, and safe sample values.
- `relationships`: flattened direct foreign-key relationships with machine-readable fields and `display_path`.
- `glossary`: versioned business glossary terms loaded from `backend/app/resources/business_glossary.yaml`.
- `cache`: cache generation, expiration, configured TTL, and whether the request explicitly refreshed the catalog.

## Safety

Only configured business schemas are exposed. PostgreSQL internal schemas and project audit-table naming patterns are excluded before table metadata is collected.

Sample values are limited to configured low-cardinality categorical text columns. The sampler also rejects likely sensitive column names, including emails, names, addresses, payment identifiers, tracking numbers, order numbers, SKUs, and similar identifiers. Sampling uses a configurable limit and per-query statement timeout. Columns that exceed the configured cardinality limit receive no samples.

The endpoint does not expose database credentials or raw database errors. Unexpected failures are handled by the backend's standard generic error response.

## Configuration

- `TEXT_TO_SQL_SCHEMA_INTROSPECTION_SCHEMAS`: exposed schema allowlist, defaulting to `commerce`.
- `TEXT_TO_SQL_SCHEMA_CACHE_TTL_SECONDS`: in-memory cache TTL, defaulting to 300 seconds.
- `TEXT_TO_SQL_SCHEMA_SAMPLE_LIMIT`: maximum distinct sample values per safe categorical column, defaulting to 20.
- `TEXT_TO_SQL_SCHEMA_SAMPLE_TIMEOUT_MS`: statement timeout for each sample query, defaulting to 1000 milliseconds.
- `TEXT_TO_SQL_SCHEMA_SAMPLE_COLUMNS`: explicit safe sample column allowlist.

