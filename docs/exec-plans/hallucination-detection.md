# ExecPlan: Hallucination Detection, Confidence, History, And Feedback

## Goal

Add a safe, explainable hallucination-detection and confidence layer to the existing
Text-to-SQL pipeline. The system should identify when generated SQL is likely to answer the
wrong business question even after passing syntactic guardrails, expose confidence evidence to
API clients, persist redacted history and feedback, and create calibration fixtures for future
evaluation.

This plan covers Prompts 16 through 20. Prompt 16 formalizes this plan only. Later prompts
implement the milestones in order.

## Non-goals

- Do not weaken or replace existing SQL guardrails, EXPLAIN planning limits, read-only
  transactions, or database role restrictions.
- Do not execute SQL that fails existing guardrails.
- Do not make the model's self-reported `model_confidence` the primary confidence signal.
- Do not store raw result rows, raw prompts, credentials, provider exception details, or sensitive
  sampled values in history, feedback, or audit logs.
- Do not expose audit/history tables through `GET /v1/schema` or grant generated SQL read access
  to those tables.
- Do not add code as part of Prompt 16.

## Current context

The backend currently provides:

- `POST /v1/query/draft` for generation-only SQL drafts.
- `POST /v1/query` for the safe end-to-end workflow.
- `QueryDraftService` for question normalization, schema retrieval, ambiguity checks, prompt
  construction, provider calls, and first-pass SQL validation.
- `QueryWorkflowService` for request orchestration and logging-based audit events.
- `QueryExecutionService` for second-pass validation, EXPLAIN inspection, read-only execution,
  bounded fetch, and rollback.
- `GeneratedSQLValidator` for PostgreSQL-aware AST validation and schema-reference extraction.
- `SQLGenerationResult.model_confidence`, currently provider-reported only.
- `HallucinationConfidenceResponse`, currently hard-coded to `status = "not_evaluated"`.
- A seeded `commerce` schema with realistic edge cases: cancelled orders, duplicate payment
  attempts, partial/full refunds, nullable payment and shipment timestamps, one-to-many line-item
  joins, and product/category bridge joins.

## What counts as hallucination in Text-to-SQL

A Text-to-SQL hallucination is any generated, safe-to-run SQL that is likely to answer a materially
different question from the user's intent. It includes:

- Schema hallucination already caught by guardrails: invented tables, invented columns, ambiguous
  references, internal schemas, and audit tables.
- Semantic schema misuse: using valid but irrelevant tables or columns, omitting expected tables or
  columns, or using the wrong date/status/money field for the question.
- Join hallucination: missing bridge tables, joining through the wrong path, multiplying facts by
  one-to-many joins, or omitting `DISTINCT`/grouping where needed.
- Aggregate hallucination: using `count(*)` when entities should be distinct, summing the wrong
  monetary amount, averaging identifiers, or grouping at a grain inconsistent with the question.
- Filter hallucination: missing explicit filters requested by the question, inventing filters not
  supported by the question, mishandling NULL semantics, or using an incorrect date range.
- Result hallucination: returning empty, all-null, duplicate-amplified, truncated, or implausibly
  shaped results without evidence that such results are expected.
- Explanation hallucination: provider explanation or back-translation claims semantics that the SQL
  does not implement.

## Signal taxonomy and evidence format

Add `backend/app/domain/confidence.py` with these public-safe domain models:

- `ConfidenceState`: `passed`, `failed`, `unavailable`, `not_applicable`.
- `ConfidenceSignalCategory`: `deterministic_validation`, `probabilistic_semantic_validation`,
  `multi_query_agreement`, `confidence_aggregation`.
- `ConfidenceSeverity`: `info`, `warning`, `error`.
- `ConfidenceEvidence`: stable `code`, public-safe `message`, `object_refs`, `measurements`,
  `thresholds`, `source`, and optional `redacted_detail`.
- `ConfidenceSignal`: stable `name`, category, state, severity, score contribution, evidence,
  duration, and optional error code.
- `ConfidenceSummary`: final state, numeric score, label, signal list, limitations, and metadata.

Evidence must be:

- Redacted and safe for API responses.
- Deterministic in tests when fake providers are used.
- Structured enough for frontend display and future eval reports.
- Never dependent on raw provider chain-of-thought or hidden prompts.

## Deterministic validation signals

Add `backend/app/services/confidence_signals.py` with pure deterministic checks that consume the
normalized question, retrieval output where available, `SQLGenerationDraft`, `SQLValidationMetadata`,
`QueryExecutionResult`, `SchemaCatalog`, and configured settings.

Required signals:

1. Schema-reference coverage
   - Compare retrieved/expected schema context with SQL AST references.
   - Pass when referenced tables and columns are a defensible subset of retrieved context plus
     required bridge tables.
   - Fail when SQL ignores high-relevance retrieved tables/columns needed by the question or uses
     only weakly related valid objects.

2. Expected-table and expected-column signals
   - Infer expected table/column families from question tokens, glossary terms, retrieval ranking,
     and schema relationships.
   - Revenue/sales should expect `orders.total_cents`, `order_items.line_total_cents`, `payments`,
     or `refunds` depending on gross/net/payment/refund wording.
   - Delivery questions should expect `shipments.shipped_at`, `shipments.delivered_at`, `carrier`,
     or `status`.
   - Product/category questions should expect the `products` and `categories` path; customer
     purchase questions should expect bridge tables through orders and order items.

3. Result sanity checks
   - Flag all-null columns, all-identical result rows, unexpected single-row results for grouped
     questions, suspiciously wide results, and truncation.
   - Treat bounded empty results as a distinct state, not automatically failure.

4. Date-range validation
   - Detect explicit year/month/range wording and compare it with SQL predicates and date functions.
   - Flag missing temporal predicates when the question asks for a range.
   - Flag likely wrong date basis, such as `ordered_at` for paid/refunded/shipped/delivered wording.
   - Use seeded fixtures for 2025/2026 and nullable timestamps.

5. NULL-heavy join detection
   - Identify nullable columns referenced in projections, filters, joins, or aggregates.
   - Flag result columns whose NULL ratio exceeds a configurable threshold.
   - Flag predicates that accidentally drop NULL-bearing lifecycle rows without question evidence,
     such as requiring `paid_at` when authorized/failed payments are relevant.

6. Duplicate-amplification detection
   - Use schema foreign keys and primary keys to detect one-to-many joins from entity questions.
   - Flag `count(*)` across `orders -> order_items`, `orders -> payments`, or similar paths when
     the question asks for orders/customers/products and SQL lacks `DISTINCT` or correct grouping.
   - Use the duplicate payment attempts in seed data as a required fixture.

7. Aggregate plausibility
   - Compare question intent with aggregate functions and result grain.
   - Flag summing IDs, averaging identifiers, counting line items for customer/order counts, or
     grouping without including requested dimensions.
   - Check that grouped result row count is plausible for known categorical samples when available.

8. Empty-result interpretation
   - Return `passed` only when SQL includes restrictive filters that plausibly explain zero rows.
   - Return `warning`/`failed` when empty result conflicts with known seeded sample values or broad
     questions such as "show all orders".
   - Return `not_applicable` for non-row-returning confidence paths and clarification outcomes.

Deterministic checks must never call LLM or embedding providers.

## Probabilistic semantic validation

Add `backend/app/providers/alignment.py` and `backend/app/services/semantic_alignment.py`.

Provider boundary:

- `AlignmentProvider` protocol:
  - `back_translate(sql, columns, sample_rows, metadata) -> BackTranslationResult`
  - `align(question, back_translation, explanation, schema_context) -> AlignmentResult`
- `FakeAlignmentProvider` for tests.
- `OpenAIAlignmentProvider` may be added later using dynamic import, bounded timeout, bounded
  retries, and structured output validation.

Back-translation:

- Convert validated SQL and a capped/redacted result sample into a concise natural-language
  description of what the SQL actually computes.
- The provider must not receive raw full result sets, credentials, raw prompts, or sensitive
  values.
- Back-translation evidence records provider name, model name, latency, token counts, and redacted
  semantic claims.

Original-question versus back-translation alignment:

- Compare the normalized user question against the back-translation and provider explanation.
- Output structured labels such as `aligned`, `partially_aligned`, `misaligned`, or
  `insufficient_evidence`, mapped to confidence states.
- Require evidence fields naming semantic mismatches: metric, table/entity, date basis, filter,
  aggregate, join path, or result grain.

Handling unavailable providers:

- Provider missing credentials, SDK missing, timeout, rate limit, malformed output, or network
  failure becomes a `ConfidenceSignal(state="unavailable")`.
- Unavailable probabilistic checks lower certainty but must not block execution.
- Public API responses must expose stable public-safe codes only.

Avoiding circular LLM self-validation:

- The primary SQL generator's stated confidence is only a weak auxiliary signal.
- Back-translation/alignment must use a separate provider interface, separate prompt template, and
  structured output schema.
- Alignment must judge SQL/result facts, not ask "is your answer correct?"
- Deterministic signals and multi-query agreement must be able to disagree with probabilistic
  output and dominate the final score when evidence is strong.

## Multi-query generation and agreement

Add `backend/app/services/multi_query_agreement.py`.

Interface:

- `MultiQueryAgreementService.evaluate(question, catalog, primary_draft, primary_execution)`
  returns a `ConfidenceSignal` plus optional redacted agreement metadata.
- It uses the existing `SQLGenerator` protocol and existing `QueryExecutionService`, so alternate
  SQL must pass the same guardrails, EXPLAIN checks, read-only role, bounded fetch, and rollback.

When multi-query validation should run:

- Request completed as `query_result`.
- Feature flag is enabled.
- Question is metric-like, aggregate-like, comparison-oriented, or high-risk by deterministic
  signals.
- Primary SQL passed guardrails and execution.
- Deterministic checks did not produce a high-severity failure that already makes agreement
  unhelpful.
- Estimated cost, row limit, provider budget, and latency budget remain available.

When multi-query validation should not run:

- Clarification required.
- Provider generation failed.
- SQL guardrails, EXPLAIN, or execution failed.
- The question is a simple row listing, lookup, or schema exploration where alternate SQL would
  add cost without meaningful evidence.
- Primary result is truncated or too large to normalize safely.
- Provider or database latency budget is exhausted.
- The SQL includes volatile functions or unsupported constructs even if read-only.
- The same model/provider output would create circular self-validation without independent
  settings, prompt, or deterministic comparison.

Agreement comparison:

- Compare normalized result signatures, not raw rows in history.
- For aggregates, compare metric columns within configurable absolute/relative tolerances.
- For categorical groupings, compare key sets and metric values after stable sorting.
- For row lists, only compare when primary keys are present and row count is bounded.
- Alternate SQL and alternate rows are not persisted by default; store hashes and summary evidence.

## Cost, timeout, and retry limits

Add settings in `backend/app/core/config.py`:

- `confidence_enabled`, default `true`.
- `confidence_semantic_enabled`, default `false` unless provider configured.
- `confidence_multi_query_enabled`, default `false`.
- `confidence_signal_timeout_ms`, default `500`.
- `confidence_total_timeout_ms`, default `2_000`.
- `confidence_alignment_timeout_seconds`, default `8.0`.
- `confidence_alignment_max_retries`, default `0`.
- `confidence_multi_query_timeout_seconds`, default `10.0`.
- `confidence_multi_query_max_alternates`, default `1`.
- `confidence_multi_query_max_additional_cost`, default derived from existing EXPLAIN thresholds.
- `confidence_result_sample_rows`, default `5`.
- `confidence_null_heavy_threshold`, default `0.8`.
- `confidence_duplicate_amplification_threshold`, default `1.25`.

If confidence work exceeds budget, remaining signals must become `unavailable` or
`not_applicable` with evidence explaining the skipped step.

## Explainable confidence scoring

Add `backend/app/services/confidence_aggregation.py`.

Rules:

- Start from deterministic evidence, not provider-stated confidence.
- Treat guardrail success as a prerequisite for query execution but not proof of semantic
  correctness.
- Apply strong penalties for deterministic failures in expected tables/columns, date range,
  duplicate amplification, and aggregate mismatch.
- Apply moderate penalties for result sanity warnings, NULL-heavy signals, empty-result ambiguity,
  and unavailable probabilistic checks.
- Use model `model_confidence` only as a small bounded feature after deterministic and agreement
  signals.
- Final summary states:
  - `passed`: no failed high-severity signals and score above threshold.
  - `failed`: one or more high-severity semantic failures or score below failure threshold.
  - `unavailable`: confidence could not run enough applicable signals.
  - `not_applicable`: clarification, blocked query, or generation-only response.

API contract changes in `backend/app/api/query.py`:

- Replace the current `HallucinationConfidenceResponse(status="not_evaluated")` placeholder for
  `POST /v1/query` with a confidence summary containing state, score, label, signals, limitations,
  and redacted evidence.
- Preserve backward-safe shape where practical by keeping `hallucination_confidence` as the top
  level response field.
- `POST /v1/query/draft` should remain generation-only; if it exposes confidence later, state must
  be `not_applicable`.

## Persistence, privacy, history, and feedback

Add database initialization changes under `database/init/`:

- Create an isolated schema such as `text_to_sql_audit`.
- Add history and feedback tables owned by the application owner.
- Do not grant `USAGE` or `SELECT` on audit/history schema to `text_to_sql_reader`.
- Keep audit/history table names excluded by existing introspection filters.

Expected modules:

- `backend/app/domain/history.py`
- `backend/app/repositories/query_history.py`
- `backend/app/services/query_history.py`
- `backend/app/api/history.py` or additional routes in `backend/app/api/query.py`
- `backend/app/core/redaction.py`

History records:

- Store request ID, timestamps, normalized question hash, optional redacted question preview,
  approved SQL hash, optional approved SQL, schema version/cache timestamp, model/provider
  telemetry, execution metadata, confidence summary, signal evidence, and outcome.
- Do not store raw rows by default.
- Do not store raw prompts, raw provider exceptions, credentials, or sensitive sampled values.
- Retention defaults should be configurable, with a conservative default such as 30 days for
  request history and 90 days for aggregate calibration metadata.

Feedback:

- Add a feedback endpoint keyed by request ID or history ID.
- Accept rating, reason codes, and optional bounded free-text comment.
- Redact comments before persistence and logging.
- Feedback cannot alter prior confidence scores in-place; it is later evaluation/calibration data.

Audit logging:

- Extend current logging-based audit events with confidence outcome, signal codes, provider
  availability, multi-query skipped/run status, and history persistence outcome.
- Logs must contain hashes and stable codes, not raw questions, rows, prompts, or sensitive values.

## Test datasets and expected failure cases

Add versioned calibration fixtures under `evals/cases/` and generated reports under
`evals/reports/`.

Required fixture families:

- Correct gross revenue by ordered month.
- Net revenue after succeeded refunds.
- Payment-based revenue versus order-based revenue.
- Date basis mismatch: ordered, paid, refunded, shipped, delivered.
- Missing requested date range.
- Nullable timestamp misuse for payments and shipments.
- Duplicate-amplified order counts through `order_items`.
- Duplicate-amplified order/payment facts through failed and retried payments.
- Product/category bridge queries requiring orders and order items.
- Aggregate mismatch: `count(*)` versus distinct customers/orders/products.
- Empty result that is expected due to a restrictive filter.
- Empty result that is suspicious for a broad known-populated table.
- Wrong valid column, such as customer region versus billing region.
- Back-translation mismatch where SQL is safe but answers a different metric.
- Multi-query agreement pass for equivalent aggregate SQL.
- Multi-query disagreement for duplicate-amplified or wrong-date SQL.
- Provider unavailable cases for alignment and embeddings.

Expected failure cases must be asserted explicitly; tests must not relax coverage to make provider
outputs pass.

## Implementation path

### Prompt 16: Formalize this plan

- Create `docs/exec-plans/hallucination-detection.md`.
- Include deterministic/probabilistic separation, signal interfaces, privacy boundaries, cost
  limits, milestones, and acceptance criteria.
- No code changes.

### Prompt 17: Deterministic signal foundation

- Add confidence domain models and deterministic signal service.
- Wire `QueryWorkflowService` to collect deterministic confidence after successful execution.
- Keep probabilistic and multi-query signals disabled/not applicable.
- Update `POST /v1/query` response models.
- Add unit tests for every deterministic signal and API serialization.

### Prompt 18: Probabilistic alignment provider boundary

- Add alignment provider protocol, fake provider, optional OpenAI adapter, settings, and service.
- Implement SQL-to-question back-translation and alignment with structured outputs.
- Map unavailable provider states to `unavailable` confidence signals.
- Add tests for timeout, malformed output, missing credentials, redaction, and non-circular
  provider prompts.

### Prompt 19: Multi-query agreement and scoring calibration

- Add multi-query agreement service using existing generator and execution pipeline.
- Implement result signature comparison and cost/latency budget enforcement.
- Add confidence aggregation weights and thresholds.
- Add calibration fixtures and evaluation report generation.
- Verify confidence is not mainly driven by provider `model_confidence`.

### Prompt 20: History, feedback, privacy hardening

- Add isolated audit/history schema and grants.
- Add history repository/service and feedback endpoint.
- Add redaction helpers, retention settings, and audit log updates.
- Prove generated SQL cannot access audit/history tables.
- Update API docs and status only at phase boundary.

## Validation commands

Prompt 16:

- `git diff --check`
- Confirm only `docs/exec-plans/hallucination-detection.md` changed.

Implementation prompts:

- `make backend-lint`
- `make backend-typecheck`
- `make backend-test`
- `make db-up`
- `make db-smoke`
- `make backend-integration-test`
- `make backend-check-integration`

Expected outcomes:

- Unit tests pass without network access.
- Integration tests pass against the seeded PostgreSQL database.
- Provider-unavailable tests are deterministic.
- History/audit tables are inaccessible to `text_to_sql_reader`.
- Existing SQL guardrail and execution tests continue to pass unchanged except for intentional
  confidence response shape updates.

## Safety and rollback

- If deterministic confidence logic misclassifies queries, disable it with `confidence_enabled`
  while preserving guardrail execution.
- If probabilistic providers are unavailable or too expensive, emit `unavailable` signals and keep
  deterministic confidence.
- If multi-query validation exceeds budgets or creates unstable evidence, disable
  `confidence_multi_query_enabled`.
- If history persistence fails, return the query result with confidence and log a redacted
  persistence failure; do not fail the executed query solely because history could not be written.
- If audit/history privilege proof fails, block deployment of Prompt 20 changes until grants are
  corrected.

## Completion criteria

- The plan is self-contained and can be implemented by a new session without conversation memory.
- Deterministic checks are separate from probabilistic provider checks and multi-query agreement.
- Confidence aggregation relies primarily on deterministic and agreement evidence, not the model's
  stated confidence.
- Provider unavailability produces stable confidence states rather than raw errors.
- Multi-query validation has explicit run/skip rules and bounded cost.
- History and feedback persistence are isolated from generated SQL and have redaction/retention
  rules.
- Calibration fixtures include both passing and expected-failure cases.
- Prompt 16 changes only this markdown plan.
