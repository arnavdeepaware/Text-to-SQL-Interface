# Prompt 9 Structured SQL Generation ExecPlan

## Goal and Non-Goals

Implement provider-neutral structured SQL draft generation. This prompt validates provider output and records provider telemetry, but does not execute generated SQL, expose an API endpoint, or perform SQL guardrail parsing.

## Current Context

Schema retrieval and prompt construction are present in the worktree. The backend environment does not currently have the OpenAI SDK installed, so the OpenAI adapter uses dynamic import and fails closed when the SDK or API key is unavailable. Tests use deterministic fake providers only.

## Implementation Path

1. Add strict SQL generation domain models in `backend/app/domain/sql_generation.py`.
2. Add a provider-neutral `SQLGenerator` protocol and typed generation errors.
3. Add deterministic fake generator for unit and integration tests.
4. Add OpenAI adapter using strict structured-output parsing when the SDK is installed.
5. Add model, timeout, retry, and output-token settings.
6. Add unit tests for strict validation, fake success/failures, OpenAI failure mapping, bounded retry, and telemetry.
7. Add integration coverage with seeded schema, prompt construction, and fake generation only.

## Safety and Rollback

The generator never executes SQL. Provider output is validated by Pydantic before being returned. Provider errors are typed and non-secret. OpenAI calls are not made in tests, and the adapter fails closed without credentials or SDK installation.

Rollback is limited to removing the SQL generation domain/provider files, tests, settings, and this plan.

## Validation

- `python3 -m uv --directory backend run pytest tests/unit/test_sql_generation.py`
- `python3 -m uv --directory backend run ruff check .`
- `python3 -m uv --directory backend run mypy`
- `python3 -m uv --directory backend run pytest -m "not integration"`
- `TEXT_TO_SQL_DATABASE_PORT=55432 python3 -m uv --directory backend run pytest --run-integration -m integration`

## Completion Criteria

- Valid structured output is accepted.
- Invalid output fails safely.
- Provider failures produce typed stable errors.
- Fake-provider tests cover successful and failed generation.
- Token and latency telemetry are captured when available.
- All checks pass.
