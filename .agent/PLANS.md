# ExecPlans

Write an ExecPlan before complex cross-cutting or security-critical work, especially changes to SQL generation, validation, database privileges, provider behavior, or evaluation policy.

Place active plans in `docs/exec-plans/`. Each plan must be self-contained and state: goal and non-goals; current context; an ordered implementation path with affected files or components; safety and rollback considerations; concrete validation commands and expected outcomes; and completion criteria. Keep the plan updated as implementation decisions change.
