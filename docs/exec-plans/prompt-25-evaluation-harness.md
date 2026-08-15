# ExecPlan: Reproducible Evaluation Harness

## Goal

Add a versioned, deterministic Text-to-SQL evaluation harness with twenty anonymized cases
against the seeded commerce database. The harness must exercise the existing guarded workflow,
produce transient reports, and make live provider use an explicit opt-in.

## Non-goals

- Do not change database schema, privileges, guardrails, or normal API provider selection.
- Do not make network calls as part of the default or CI evaluation path.
- Do not treat SQL string equality as the correctness oracle.

## Current Context

The project already has deterministic seed data, a `QueryWorkflowService`, SQL guardrails,
read-only execution, and a `FakeSQLGenerator`. `evals/cases` and `evals/reports` are placeholders.

## Implementation Path

1. Add strict Pydantic case and result models plus a JSON dataset loader.
2. Add a scripted fake SQL provider keyed by normalized question for deterministic evaluation.
3. Add an evaluation service and CLI that call the existing schema, workflow, and execution services.
4. Add twenty versioned JSON cases covering valid, ambiguous, unsupported, destructive, and
   hallucination-prone questions.
5. Add JSON/Markdown reports under ignored `evals/reports`, Make targets, tests, and CI coverage.

## Safety And Rollback

The runner uses the application read-only database role and existing guardrails. Unsafe scripted
SQL is expected to fail before execution. Reports contain only fixture questions, SQL, expected
and observed results, and public-safe error codes; they are untracked transient artifacts. Removing
the new evaluator modules, targets, and fixtures fully rolls back this work without data migration.

## Validation

Run `make eval-validate`, `make db-up`, `make eval-run`, `make backend-check`, and `make check`.
The default provider must make no network calls; all twenty cases must meet their declared outcome;
unsafe generated SQL must be blocked; and report files must be ignored by Git.

## Completion Criteria

The project has a strict v1 case contract, twenty runnable cases, deterministic fake evaluation,
explicit live opt-in, JSON and Markdown reports, focused evaluator tests, and a passing complete
project check.
