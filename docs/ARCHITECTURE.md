# Current Architecture

## Request lifecycle

1. React submits a natural-language question to FastAPI.
2. The schema catalog introspects the configured `commerce` schema, caches safe metadata, and retrieves relevant tables, columns, glossary terms, and foreign-key paths.
3. The prompt engine renders retrieved context, safe samples, relationship paths, and selected resource-backed examples. Expected evaluation SQL is never included in evaluated prompts.
4. Known business ambiguities are detected before provider calls. The API returns clarification options for revenue meaning, date basis, location, refunds, and order status.
5. A provider returns structured SQL, explanation, references, assumptions, confidence, and telemetry. Fake providers are deterministic; live providers are opt-in.
6. SQLGlot parses PostgreSQL SQL. Guardrails enforce one read-only statement, schema/table/column policy, safe structure, and bounded output.
7. The executor runs `EXPLAIN (FORMAT JSON)` and rejects plans over configured cost, row, relation, or timeout limits.
8. Approved SQL executes in a read-only transaction with statement and lock timeouts, row limits, and rollback behavior.
9. Signals and confidence are calculated. The API returns SQL, rows, execution metadata, guardrail findings, confidence, warnings, and provider metadata.
10. History stores redacted normalized questions, approved SQL when available, outcomes, metadata, and feedback in an isolated audit schema.

## Components

- `backend/app/api`: health, schema, draft, execution, history, and feedback contracts.
- `backend/app/core`: settings, logging, redaction, and security primitives.
- `backend/app/domain`: query, schema, evaluation, confidence, history, and guardrail models.
- `backend/app/providers`: fake/scripted, OpenAI, embedding, and alignment adapters.
- `backend/app/services`: retrieval, prompting, workflow, validation, execution, confidence, history, and evaluation.
- `database/init`: reproducible schema, synthetic seed data, audit schema, and roles.
- `frontend/src`: query workspace, results, confidence, history, feedback, and accessible states.
- `evals/cases`: versioned fixtures; `evals/reports`: ignored generated output.

## Trust boundaries

The backend, not the browser or provider, owns authorization and execution. The generated-query role can select only named commerce tables and cannot access `text_to_sql_audit`. The audit-writer role can write audit tables but cannot read commerce data. The owner role is initialization-only.

Static validation, plan inspection, and database privileges are independent defenses. A provider that emits valid-looking destructive SQL still cannot write because it never receives write privileges and AST policy rejects it before execution.

## Signals and confidence

Deterministic signals cover SQL syntax, guardrail approval, schema coverage, provider metadata agreement, result sanity, and execution evidence. Optional semantic back-translation and multi-query agreement are represented as passed, failed, unavailable, or not applicable. Confidence aggregates configured weights, treats critical missing evidence as unavailable, caps provider-reported confidence at a small auxiliary weight, and forces a blocked band for hard failures.

## Privacy and operational boundaries

History excludes raw result rows, raw prompts, credentials, stack traces, and full provider responses by design. Likely secrets are redacted before persistence, but this is not complete DLP. Retention durations are configuration placeholders; automated deletion is not implemented.

Compose provides PostgreSQL, backend, and frontend healthchecks, startup dependencies, local fake-provider defaults, bounded resources, and non-root application containers. It is intended for local demonstration and CI, not production deployment.
