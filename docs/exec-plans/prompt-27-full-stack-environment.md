# Prompt 27: Full-Stack Environment

## Goal and non-goals

Provide a deterministic Docker Compose environment for PostgreSQL, FastAPI, and the React
frontend. It must exercise the existing safe query workflow through the frontend proxy. This plan
does not add live-model evaluation or production deployment infrastructure.

## Implementation path

1. Add backend and frontend multi-stage container support, run application containers as non-root,
   and make nginx proxy same-origin API requests to the backend.
2. Extend Compose with backend and frontend services, database-aware readiness, startup health
   dependencies, bounded connection timeouts, and fake demo provider configuration.
3. Split database owner, read-only query, and audit-writer credentials. Initialization owns DDL;
   runtime audit access receives only the required DML grants.
4. Add a container-internal smoke command that checks frontend delivery, proxied backend health,
   a seeded safe query, and generated unsafe SQL rejection.
5. Run the full deterministic stack and smoke command in CI after existing quality checks.

## Safety and rollback

Generated SQL continues to use only the reader role. The unsafe fixture is deliberately produced
by the deterministic fake provider and must fail SQL validation before execution. `make stack-down`
preserves data; `make stack-reset` deliberately removes only the named local Compose volume.

## Validation and completion

Run `make compose-check`, `make backend-check`, `make frontend-check`, `make db-smoke`, `make
backend-integration-test`, `make eval-run`, `make stack-reset`, and `make stack-smoke`. Completion
requires all three containers healthy, exact seeded safe results, and a blocked unsafe result.
