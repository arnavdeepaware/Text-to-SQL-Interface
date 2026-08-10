# Project Status

## Phase 0 — Foundation

**Status:** Complete

The repository foundation is in place: contributor instructions, architecture documentation, roadmap, FastAPI health checks, PostgreSQL schema and deterministic seed data, backend database connectivity, and local/CI quality checks.

## Phase 1 — Schema-Aware Generation

**Status:** Complete

The backend now introspects the commerce schema, enriches it with safe categorical samples and glossary context, retrieves relevant tables and columns for user questions, detects known business ambiguities, builds schema-aware prompts, and generates structured SQL drafts through the provider abstraction.

## Phase 2 — Guardrails And Read-Only Execution

**Status:** Complete

Generated SQL is parsed with PostgreSQL-aware AST validation, schema references are checked against the introspected catalog, structural guardrail rules fail closed, result size is bounded through AST LIMIT rewriting, EXPLAIN JSON plans are inspected against configurable cost and row thresholds, and approved queries execute only through the read-only application role inside read-only transactions with rollback. `POST /v1/query` provides the safe end-to-end Text-to-SQL workflow with SQL, explanation, tabular results, execution metadata, guardrail metadata, and model metadata.

## Phase 3 — Hallucination Detection And Confidence

**Status:** Complete

The backend now emits explainable validation signals for schema coverage, provider metadata
agreement, result sanity, SQL-to-question back-translation alignment, and optional multi-query
agreement. `POST /v1/query` calculates a deterministic confidence summary with configurable
weights and thresholds, explicit high/medium/low/blocked bands, signal breakdowns, warnings, and a
concise rationale. Confidence scoring treats unavailable evidence separately from failed evidence,
keeps provider-reported model confidence as a small bounded auxiliary input, and preserves the
existing fail-closed guardrail and read-only execution boundary.

## Phase 4 — Query History, Feedback, And Privacy

**Status:** Complete

The backend now persists redacted query audit records and user feedback in an isolated
`text_to_sql_audit` schema that is separate from the generated-SQL commerce dataset. Query history
stores request IDs, normalized questions, approved SQL when available, outcomes, blocked reason
codes, execution metadata, confidence summaries, provider telemetry, and timestamps without raw
rows, raw prompts, credentials, stack traces, or full provider responses. `GET /v1/history` exposes
paginated history with retention and privacy-limit placeholders, and `POST /v1/feedback` records
correct/incorrect/unsure feedback linked to a query audit record. The generated-query reader role is
explicitly denied access to audit tables.

## Next phase

Phase 5 should add frontend result presentation, broader adversarial eval reports, automated
retention enforcement, and release-readiness hardening without weakening the established read-only
execution boundary.
