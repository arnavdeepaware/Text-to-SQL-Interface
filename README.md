# Text-to-SQL Interface

A portfolio-quality Text-to-SQL system that turns natural-language questions into safe, schema-aware, read-only PostgreSQL queries. It is designed around guardrails, hallucination detection, confidence scoring, and repeatable evaluation.

## Intended architecture

- `backend/` — FastAPI service, domain logic, database access, and tests.
- `database/` — local database initialization assets.
- `evals/` — evaluation cases and generated reports.
- `frontend/` — React and TypeScript user interface.
- `docs/` — architecture, roadmap, ADRs, and execution plans.

The root-level Python prototype is existing exploratory work; the planned implementation lives in the directories above.

## Status

Phase 5 (evaluation and hardening) is in progress. See [docs/STATUS.md](docs/STATUS.md), [docs/ROADMAP.md](docs/ROADMAP.md), and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Setup

Install the backend toolchain with uv:

```bash
make backend-install
```

Install the frontend toolchain with npm:

```bash
make frontend-install
```

Start local PostgreSQL when you need database-backed checks:

```bash
make db-up
make db-smoke
```

The backend reads `TEXT_TO_SQL_DATABASE_*` variables and defaults to the local Docker read-only role. Keep real overrides in `.env`; `.env.example` lists variable names only.

## Full stack

Start the complete deterministic demo stack with one command:

```bash
docker compose up --build
```

Or run it in the background and wait for all service healthchecks:

```bash
make stack-up
make stack-smoke
```

The frontend is available at `http://localhost:8080`; it proxies API requests to the backend. The
backend connects to PostgreSQL with the read-only query role and a separate, restricted audit-writer
role. PostgreSQL owner credentials remain inside the database service for initialization only.

Useful local commands:

```bash
make stack-logs       # follow PostgreSQL, backend, and frontend logs
make stack-down       # stop services and retain the seeded volume
make stack-reset      # remove the volume, rebuild, and reseed deterministically
```

If startup remains unhealthy, inspect `make stack-logs`; a stale volume may have been initialized
with older role credentials, in which case use `make stack-reset`. The default fake demo provider
does not make network calls. To use a live provider, explicitly set
`TEXT_TO_SQL_SQL_GENERATION_PROVIDER=openai` and `TEXT_TO_SQL_OPENAI_API_KEY` in an untracked
`.env` file; no API key is included in an image or tracked configuration.

## Development

Start the FastAPI backend locally:

```bash
make backend-dev
```

Start the Vite frontend locally:

```bash
make frontend-dev
```

The frontend reads `VITE_API_BASE_URL` at build and dev-server time. Leave it unset when the
frontend is served behind the same origin as the API, or set it to a backend origin such as
`http://localhost:8000` during local split-server development.

Run focused backend checks while developing:

```bash
make backend-test
make backend-lint
make backend-typecheck
```

Run focused frontend checks while developing:

```bash
make frontend-test
make frontend-lint
make frontend-build
```

Validate Docker Compose:

```bash
make compose-check
```

Run the opt-in database integration tests after PostgreSQL is running:

```bash
make backend-integration-test
```

Run the complete backend check before finishing backend work:

```bash
make backend-check
```

Run the complete frontend check before finishing frontend work:

```bash
make frontend-check
```

To include database integration tests in the complete backend pass:

```bash
make backend-check-integration
```

Mirror the main CI checks locally:

```bash
make check
make db-down
```

`make check` validates Compose, runs Ruff, mypy, unit tests, starts PostgreSQL, smoke-tests the seed database, and runs integration tests. `make db-down` stops the local database afterward.

## Evaluation

The versioned seeded-commerce suite has 50 distinct cases across execution, ambiguity,
unsupported-question, malformed-request, guardrail, and hallucination scenarios. It uses a
deterministic scripted fake generator by default, runs through the normal guardrail and read-only
execution path, and writes transient JSON plus a concise portfolio-summary Markdown report to
`evals/reports/`.

```bash
make eval-validate
make db-up
make eval-run
```

SQL exact match is reported as a diagnostic. Result matching against the seeded database is the
primary correctness metric for executable cases; the report also covers ambiguity and unsupported
question handling, label-backed hallucination precision/recall, guardrail effectiveness, and unsafe
query escapes. Live evaluation is intentionally not a Make target; it requires `--provider openai
--allow-live` and `TEXT_TO_SQL_EVAL_ALLOW_LIVE=true`.

## Security

Generated SQL must be schema-validated, bounded, and executed only through a least-privilege read-only database role.
