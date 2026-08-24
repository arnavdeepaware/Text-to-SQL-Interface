# Interview Talk Track

## Opening

“I built a Text-to-SQL system where SQL generation is an untrusted proposal. The interesting problem is deciding whether a query is answerable, safe, resource-bounded, and semantically aligned enough to show to a user.”

## Architecture

Describe four layers: schema-aware retrieval and prompt construction; structured provider output; backend-owned AST, schema, and plan validation; and read-only execution with confidence and audit metadata. The browser never authorizes SQL.

## Tradeoffs

- **Result match over SQL exact match:** equivalent SQL can differ textually, so exact match is diagnostic.
- **Fake provider by default:** deterministic fixtures make CI reproducible and prove the evaluator and safety path, but cannot measure live-model generalization.
- **Defense in depth:** AST rejection catches unsafe structure while database privileges limit impact if an implementation mistake remains.
- **Lexical retrieval first:** it is deterministic and inspectable; optional embeddings can improve recall but add dependency and failure modes.
- **Confidence as evidence, not truth:** validation signals and missing evidence are visible; provider confidence has only a small bounded weight.

## Likely questions

**What happens when the model invents a table?** Schema and column allowlists reject it; the public response contains a stable reason instead of raw provider output.

**Can a generated `DELETE` run?** No. AST policy rejects non-read-only statements and the query role has no write privilege.

**Why is result match 92%?** Two intentional semantic-mismatch fixtures execute but do not match the expected answer. Syntax and execution success are insufficient.

**What do the hallucination metrics mean?** They are label-backed metrics over eligible cases: 10 true positives, 13 predicted positives, and 11 labeled positives in the latest report. They are not a general hallucination rate.

**What are the main failure modes?** Ambiguous business language, unsupported questions, malformed output, schema hallucination, unsafe statements, expensive plans, provider timeouts/rate limits, database unavailability, and audit persistence failure.

**What comes before production?** Authentication and tenant isolation, managed secrets and TLS, migrations/backups, automated retention, rate limiting, monitoring, a supported live-provider dependency, and a separately versioned live benchmark.

## Closing

“The strongest claim is not that the model is always right. It is that the system makes uncertainty and failure visible, limits what can execute, and measures the behavior it can actually reproduce.”
