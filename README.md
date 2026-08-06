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

Phase 0 (repository foundation) is in progress. See [docs/STATUS.md](docs/STATUS.md), [docs/ROADMAP.md](docs/ROADMAP.md), and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Setup

Install the backend toolchain with uv:

```bash
make backend-install
```

Start local PostgreSQL when you need database-backed checks:

```bash
make db-up
make db-smoke
```

The backend reads `TEXT_TO_SQL_DATABASE_*` variables and defaults to the local Docker read-only role. Keep real overrides in `.env`; `.env.example` lists variable names only.

## Development

Start the FastAPI backend locally:

```bash
make backend-dev
```

Run focused checks while developing:

```bash
make backend-test
make backend-lint
make backend-typecheck
```

Run the opt-in database integration tests after PostgreSQL is running:

```bash
make backend-integration-test
```

Run the complete backend check before finishing backend work:

```bash
make backend-check
```

To include database integration tests in the complete backend pass:

```bash
make backend-check-integration
```

## Evaluation

Placeholder — curated cases and evaluation reports will live under `evals/`.

## Security

Generated SQL must be schema-validated, bounded, and executed only through a least-privilege read-only database role.
