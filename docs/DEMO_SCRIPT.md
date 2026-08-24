# Demo Script: Under Four Minutes

Use the local fake-provider stack so the walkthrough is reproducible and makes no network calls. Before the timer, run `make stack-up`.

## 0:00–0:30: Frame the problem

Open `http://localhost:8080`. Say: “The system turns business questions into read-only SQL, but treats the model as an untrusted proposal source. The backend owns validation, execution, confidence, history, and blocking.”

## 0:30–1:10: Normal question

Submit `List cancelled orders for the demo smoke test`. Point out the generated SQL, the two result rows, the `fake` provider label, execution metadata, and confidence breakdown.

## 1:10–1:45: Ambiguity

Submit `Show revenue by month`. Show clarification between gross revenue before refunds and net revenue after succeeded refunds. Say: “The system does not silently choose a business definition that changes the answer.”

## 1:45–2:20: Destructive-query block

Submit `Show cancelled orders for the unsafe smoke test`, or run `make stack-smoke`. Show the blocked result and `sql_validation_failed`. Explain that the fixture emits a `DELETE`, while AST policy and the read-only role provide independent protection.

## 2:20–2:55: Hallucination discrepancy

After `make eval-run`, open `evals/reports/latest.md` and show `semantic_mismatch_delivered_orders` or `semantic_partial_refund_mismatch`: it executes, but result and SQL exact match are false. Say: “Syntactically valid SQL is not automatically semantically correct.”

## 2:55–3:25: Evaluation and confidence

Explain that the latest fake-provider run has 50 declared outcomes, 23/25 executable result matches, 13/13 ambiguity accuracy, 10/13 hallucination precision, and zero unsafe escapes. These are scripted fixture metrics, not live-model accuracy. Point to schema coverage, result sanity, guardrail approval, optional semantic alignment, and the small model-confidence contribution.

## 3:25–3:55: Feedback and history

Mark the query as correct, open recent history, and show redacted audit metadata and the confidence summary. Close with synthetic data, no published live benchmark, optional retention enforcement, and remaining production deployment work.
