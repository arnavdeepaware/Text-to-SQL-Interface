# Project Status

## Complete

- Foundation, contributor guidance, FastAPI health endpoints, PostgreSQL schema, deterministic seed data, and local/CI checks.
- Schema introspection, safe sample selection, glossary and relationship retrieval, deterministic lexical retrieval, and schema-aware prompts.
- Structured providers, ambiguity handling, draft generation, and stable public errors.
- PostgreSQL-aware AST validation, schema allowlisting, SELECT-only policy, bounded results, EXPLAIN cost/row checks, read-only transactions, timeouts, and rollback.
- Explainable hallucination and confidence signals, including schema coverage, metadata agreement, result sanity, optional semantic alignment, and optional multi-query agreement.
- Redacted audit history and feedback in an isolated schema with separate owner, query-reader, and audit-writer roles.
- React/TypeScript workspace with SQL transparency, results, confidence, blocked states, clarification, history, feedback, responsive layouts, and accessibility coverage.
- Docker Compose with PostgreSQL, FastAPI, React/Nginx, health ordering, fake-provider demo mode, and deterministic safe/unsafe smoke tests.
- Versioned 50-case evaluation suite with JSON/Markdown reports, evaluator tests, ignored transient artifacts, and explicit live-provider opt-in.

## Latest measured evaluation

The generated report is deterministic fake-provider evidence for `seeded_commerce_core` v1. It reports 50/50 declared outcomes, 23/25 result matches, 23/25 SQL exact matches, 13/13 ambiguity accuracy, 7/7 unsupported-question handling, 10/13 hallucination precision, 10/11 hallucination recall, 10/10 generated-query guardrail effectiveness, and zero unsafe-query escapes. SQL exact match is diagnostic; result matching is primary. No live-model benchmark is published.

## Optional or remaining

- Live provider evaluation and embedding retrieval require explicit configuration and are not part of default CI.
- Automated history and feedback retention enforcement is not implemented.
- Authentication, authorization, multi-tenancy, production secret management, TLS, managed deployment, backups, migrations, and operational monitoring remain deployment work.
- Broader adversarial evaluation, provider comparison, richer telemetry, and release hardening are future improvements.
