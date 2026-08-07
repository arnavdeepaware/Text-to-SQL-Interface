# Prompt 7 Schema Retrieval ExecPlan

## Goal and Non-Goals

Build a provider-neutral schema retrieval layer that selects tables, columns, glossary terms, and foreign-key paths relevant to a natural-language question.

This work does not call an LLM, generate SQL, execute SQL, expose a new HTTP endpoint, or require an OpenAI API key.

## Current Context

The backend already has typed schema introspection, a cached schema catalog, safe sample values, and a bundled business glossary. Retrieval should consume those domain objects and return inspectable domain output for later SQL generation and confidence scoring.

Provider integrations belong in `backend/app/providers`; orchestration belongs in `backend/app/services`; HTTP contracts are not changed for this prompt.

## Implementation Path

1. Add retrieval domain models in `backend/app/domain/schema_retrieval.py`.
2. Add an `EmbeddingProvider` protocol and OpenAI embedding adapter in `backend/app/providers/embeddings.py`.
3. Add retrieval settings to `backend/app/core/config.py`.
4. Implement deterministic lexical retrieval in `backend/app/services/schema_retrieval.py`.
5. Preserve foreign-key relationship paths and include required bridge tables within configured hop and table limits.
6. Add unit tests for requested question families, bridge behavior, deterministic ranking, and embedding fallback.
7. Add Docker-backed integration coverage against the seeded PostgreSQL schema.
8. Document retrieval behavior in `docs/SCHEMA_RETRIEVAL.md`.

## Safety and Rollback

The retriever is read-only over in-memory schema metadata. It does not execute database queries, call an LLM, or generate SQL.

The OpenAI adapter is disabled unless `TEXT_TO_SQL_OPENAI_API_KEY` is configured and retrieval embeddings are explicitly enabled. Tests use fake providers and do not require network access.

Rollback is limited to removing the new retrieval/provider modules, settings, tests, and docs.

## Validation

Expected passing commands:

- `python3 -m uv --directory backend run pytest tests/unit/test_schema_retrieval.py`
- `python3 -m uv --directory backend run ruff check .`
- `python3 -m uv --directory backend run mypy`
- `python3 -m uv --directory backend run pytest -m "not integration"`
- `python3 -m uv --directory backend run pytest --run-integration -m integration`

Integration tests require the Docker PostgreSQL service to be running.

## Completion Criteria

- Retrieval is deterministic in tests.
- Missing or failing embedding configuration degrades to lexical retrieval.
- Ranked tables, ranked columns, scores, reasons, glossary matches, and relationship paths are returned.
- Required bridge tables are included when selected tables need foreign-key paths.
- Unit, integration, lint, and type checks pass.
