# Project Status

## Phase 0 — Foundation

**Status:** Complete

The repository foundation is in place: contributor instructions, architecture documentation, roadmap, FastAPI health checks, PostgreSQL schema and deterministic seed data, backend database connectivity, and local/CI quality checks.

## Phase 1 — Schema-Aware Generation

**Status:** Complete

The backend now introspects the commerce schema, enriches it with safe categorical samples and glossary context, retrieves relevant tables and columns for user questions, detects known business ambiguities, builds schema-aware prompts, and generates structured SQL drafts through the provider abstraction.

## Phase 2 — Guardrails And Read-Only Execution

**Status:** Complete

Generated SQL is parsed with PostgreSQL-aware AST validation, schema references are checked against the introspected catalog, structural guardrail rules fail closed, result size is bounded through AST LIMIT rewriting, EXPLAIN JSON plans are inspected against configurable cost and row thresholds, and approved queries execute only through the read-only application role inside read-only transactions with rollback. `POST /v1/query` now provides the first safe end-to-end Text-to-SQL workflow with SQL, explanation, tabular results, execution metadata, guardrail metadata, model metadata, and hallucination confidence explicitly marked `not_evaluated`.

## Next phase

Phase 3 should add hallucination/confidence evaluation, broader adversarial eval cases, and frontend result presentation without weakening the established read-only execution boundary.
