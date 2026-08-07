# Query Draft API

`POST /v1/query/draft` returns a generation-only Text-to-SQL result. It never executes SQL.

## Request

```json
{
  "question": "Calculate net revenue",
  "refresh_schema": false
}
```

The question is normalized by trimming and collapsing whitespace. Empty questions return a stable `empty_question` error. Questions longer than `TEXT_TO_SQL_QUERY_MAX_QUESTION_CHARS` return `question_too_long`.

## Responses

The endpoint returns one of two typed results.

### SQL Draft

```json
{
  "result_type": "sql_draft",
  "request_id": "request-id",
  "question": "Calculate net revenue",
  "sql": "SELECT ...",
  "explanation": "Draft explanation.",
  "metadata": {
    "model_confidence": 0.8,
    "tables_used": ["commerce.orders"],
    "columns_used": ["commerce.orders.total_cents"],
    "assumptions": [],
    "telemetry": {
      "provider_name": "fake",
      "model_name": "fake-sql-generator",
      "provider_latency_ms": 7,
      "input_tokens": 111,
      "output_tokens": 33,
      "total_tokens": 144,
      "retry_count": 0
    }
  }
}
```

### Clarification Required

```json
{
  "result_type": "clarification_required",
  "request_id": "request-id",
  "question": "Show revenue by month",
  "message": "The question is materially ambiguous. Choose an interpretation before SQL is generated.",
  "clarification_options": [
    {
      "interpretation": "Gross revenue before refunds",
      "example": "Show gross revenue by ordered month"
    },
    {
      "interpretation": "Net revenue after succeeded refunds",
      "example": "Show net revenue by ordered month"
    }
  ]
}
```

Known business ambiguities are detected before provider calls: revenue meaning, date basis, customer location, refund handling, and order status. The configured generator may also return `clarification_needed`, which the endpoint converts to the same clarification response shape.

## Errors

Public errors preserve the stable shape:

```json
{
  "error": {
    "code": "empty_question",
    "message": "Question must not be empty.",
    "request_id": "request-id"
  }
}
```

Provider timeout, rate limiting, malformed output, unavailable credentials, and unavailable provider states are mapped to stable public error codes. Raw provider errors and credentials are never exposed.
