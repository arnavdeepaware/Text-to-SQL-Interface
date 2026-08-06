# Repository Instructions

## Purpose and architecture

This repository will deliver a safe, portfolio-quality Text-to-SQL system. The intended architecture is a FastAPI backend with explicit domain and service layers, PostgreSQL accessed through SQLAlchemy 2, evaluation fixtures, and a React/TypeScript interface. Generated SQL is schema-aware, validated, confidence-scored, and executed through a read-only role.

## Important directories

- `backend/`: API, domain, services, persistence adapters, and backend tests.
- `database/`: PostgreSQL initialization assets.
- `evals/`: versioned evaluation cases and generated reports.
- `frontend/`: React UI and TypeScript code.
- `docs/`: architecture, ADRs, plans, roadmap, and status.
- `.agent/PLANS.md`: ExecPlan requirements and format.

## Engineering rules

- Target Python 3.11+ with FastAPI, SQLAlchemy 2, Pydantic 2, and PostgreSQL; target React and TypeScript for the frontend; use Docker Compose for local orchestration.
- Always inspect existing code before modifying it. Keep tasks scoped; avoid unrelated refactors.
- Never commit, push, amend, reset, or rewrite Git history.
- Never place secrets or API keys in tracked files.
- Add or update tests for behavior changes. Run the smallest relevant checks first, then the complete project check command before finishing. Do not weaken tests merely to make them pass.
- Security-sensitive SQL code must fail closed. Generated queries must never receive write privileges.
- Use an ExecPlan from `.agent/PLANS.md` for complex cross-cutting or security-critical work.
- Update `docs/STATUS.md` only at phase boundaries.

Nested `AGENTS.md` files add directory-specific rules; this file remains authoritative where guidance conflicts.
