# Intended Architecture

## Request path

1. The React interface submits a natural-language question to the FastAPI API.
2. The API passes it to an orchestration service that retrieves an allowlisted schema context.
3. A provider adapter proposes SQL and structured reasoning metadata.
4. Guardrails parse and validate the query against policy and schema; ambiguous or unsupported output is rejected.
5. A hallucination detector checks referenced tables, columns, joins, and answer alignment.
6. A confidence service combines model and deterministic validation signals.
7. Only an approved query runs through a PostgreSQL read-only role with time, row, and cost bounds.
8. The API returns results, SQL, confidence, and any limitations to the UI; redacted audit history
   and feedback are recorded without secrets.

## Components

- `backend/app/api`: request contracts and HTTP endpoints.
- `backend/app/core`: configuration, policy, logging, and security primitives.
- `backend/app/domain`: SQL/query, schema, confidence, and evaluation models.
- `backend/app/providers`: LLM provider abstractions and implementations.
- `backend/app/services`: generation, validation, execution, and scoring workflows.
- `backend/app/services/schema_retrieval.py`: provider-neutral schema-context retrieval for
  natural-language questions, including deterministic lexical ranking and preserved
  foreign-key bridge paths.
- `backend/app/services/prompt_engine.py`: provider-neutral prompt construction using retrieved
  schema context, safe samples, glossary terms, relationship paths, and resource-backed few-shot
  examples.
- `backend/app/api/query.py`: generation-only SQL draft endpoint with deterministic ambiguity
  handling, request IDs, and stable public errors. SQL execution is out of scope.
- `backend/app/api/history.py`, `backend/app/services/query_history.py`, and
  `backend/app/repositories/query_history.py`: redacted query history and feedback capture backed
  by isolated audit tables.
- `backend/app/repositories` and `backend/app/db`: schema metadata and database access.
- `database/init`: reproducible local PostgreSQL setup.
- `evals/cases`: curated fixtures; `evals/reports`: generated evaluation output.
- `frontend/src`: query experience and safe presentation of outcomes.

## Security boundary

The backend, not the frontend or model provider, owns authorization and execution. Reject on validation uncertainty. Generated SQL may only be read-only and must execute with least privilege.

Audit/history data lives in `text_to_sql_audit`, outside the schemas exposed to generated SQL.
The generated-query role is granted only named commerce tables and is explicitly denied access to
audit tables. The redaction layer masks likely secrets, but it is a configurable safeguard rather
than a complete data-loss-prevention system.
