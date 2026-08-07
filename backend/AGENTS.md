# Backend Instructions

Follow the root `AGENTS.md`. Keep HTTP handling in `app/api`, configuration and security policy in `app/core`, persistence concerns in `app/db` and `app/repositories`, provider integrations in `app/providers`, and business orchestration in `app/services`.

Use Python 3.11+, FastAPI, SQLAlchemy 2, Pydantic 2, and PostgreSQL when implementation begins. Put focused tests in `tests/unit` and boundary tests in `tests/integration`. SQL validation or execution changes are security-critical and require an ExecPlan.
When the user explicitly asks, it is okay to commit and push changes.
