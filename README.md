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

Placeholder — dependencies and application setup will be added in a later phase.

## Development

Placeholder — follow [AGENTS.md](AGENTS.md) and run the smallest relevant check before broader validation.

## Evaluation

Placeholder — curated cases and evaluation reports will live under `evals/`.

## Security

Generated SQL must be schema-validated, bounded, and executed only through a least-privilege read-only database role.
