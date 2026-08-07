# Prompt 8 Schema-Aware Prompt Engine ExecPlan

## Goal and Non-Goals

Build a deterministic prompt-construction layer for Text-to-SQL generation. The layer packages the original question, retrieved schema context, safe samples, relationships, glossary definitions, SQL dialect, strict read-only rules, structured-output requirements, and relevant few-shot examples.

This work does not call an LLM, generate SQL dynamically, execute SQL, expose a new endpoint, or log secrets.

## Current Context

The backend has typed schema introspection, safe sampling, a business glossary, and an uncommitted schema retriever that returns selected tables, columns, and relationship paths. Prompt construction should consume those domain objects and produce provider-neutral prompt messages.

## Implementation Path

1. Add prompt domain models in `backend/app/domain/prompt.py`.
2. Store schema-specific few-shot examples in `backend/app/resources/few_shot_examples.json`.
3. Add a JSON loader and validator in `backend/app/services/few_shot_loader.py`.
4. Add a prompt engine in `backend/app/services/prompt_engine.py`.
5. Add prompt configuration to `backend/app/core/config.py`.
6. Add golden/snapshot-style unit tests for representative prompts, relevance, truncation, missing glossary, and secret-safe logging metadata.
7. Document the prompt engine in `docs/PROMPT_ENGINE.md` and update architecture docs.

## Safety and Rollback

The prompt engine is read-only over in-memory domain objects. It never accesses database credentials, calls providers, executes SQL, or logs complete prompts by default. Few-shot SQL is static resource text for prompting only.

Rollback is limited to removing the prompt domain, loader, engine, resource, docs, and tests.

## Validation

Expected passing commands:

- `python3 -m uv --directory backend run pytest tests/unit/test_prompt_engine.py tests/unit/test_few_shot_loader.py`
- `python3 -m uv --directory backend run ruff check .`
- `python3 -m uv --directory backend run mypy`
- `python3 -m uv --directory backend run pytest -m "not integration"`
- `TEXT_TO_SQL_DATABASE_PORT=55432 python3 -m uv --directory backend run pytest --run-integration -m integration`

## Completion Criteria

- Prompts include only retrieved schema context.
- Foreign-key relationships, selected paths, safe samples, glossary definitions, SQL dialect, read-only rules, and structured-output instructions are explicit.
- Few-shot examples load from a resource and are selected deterministically by relevance.
- Context budget enforcement is deterministic and covered by tests.
- Unit, integration, lint, and type checks pass.
