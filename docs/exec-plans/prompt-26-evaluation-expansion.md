# ExecPlan: Expanded Golden Evaluation Suite

## Goal

Expand the seeded-commerce evaluation suite from twenty to at least fifty genuinely distinct cases
and report ground-truth-backed portfolio metrics for routing, safety, correctness, and available
hallucination signals.

## Non-goals

- Do not alter production guardrails, database privileges, or the normal API provider path.
- Do not run a live model as part of development, CI, or the deterministic regression suite.
- Do not gate regressions on exploratory metrics whose labels or denominators are incomplete.

## Implementation Path

1. Extend the v1 case contract for malformed requests and stable safety thresholds.
2. Add result-independent routing and safety metrics to the report, including explicit unavailable
   values when hallucination labels do not permit precision/recall.
3. Add thirty-two distinct cases over the deterministic seed data, including semantic-mismatch and
   unsafe SQL fixtures.
4. Expand evaluator tests, report output, README guidance, and CI validation.

## Safety And Validation

The scripted provider receives only normalized questions and never receives expected SQL or
results. The runner continues to use the production schema retrieval, SQL guardrails, query plan
inspection, and read-only executor. Validate with `make eval-validate`, `make eval-run`, and
`make check`; all fake-provider cases must remain deterministic and unsafe-query escapes must stay
at zero.

## Completion Criteria

At least fifty cases run locally, reports contain diagnosable per-case outcomes and portfolio
metrics, live evaluation remains double-opt-in, and the full repository check passes.
