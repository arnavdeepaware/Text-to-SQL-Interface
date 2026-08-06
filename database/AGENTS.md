# Database Instructions

Follow the root `AGENTS.md`. Keep reproducible, reviewable PostgreSQL initialization artifacts in `init/`; do not add credentials, production data, or destructive operational scripts.

Design roles and grants so generated SQL has read-only access only. Treat every schema or privilege change as security-sensitive and use an ExecPlan when it affects cross-cutting behavior.
