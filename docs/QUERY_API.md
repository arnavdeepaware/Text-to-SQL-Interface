# Query API

Examples assume `make stack-up` and the frontend proxy at `http://localhost:8080`.

## Health

```bash
curl -s http://localhost:8080/health
curl -s http://localhost:8080/ready
```

## Draft without execution

`POST /v1/query/draft` validates and returns a SQL draft but never executes it:

```bash
curl -s http://localhost:8080/v1/query/draft \
  -H 'content-type: application/json' \
  -d '{"question":"Calculate net revenue"}'
```

Result types are `sql_draft` and `clarification_required`. Empty or overlong questions return a stable error with `code`, `message`, and `request_id`.

## Guarded execution

```bash
curl -s http://localhost:8080/v1/query \
  -H 'content-type: application/json' \
  -H 'x-request-id: docs-safe-query' \
  -d '{"question":"List cancelled orders for the demo smoke test"}'
```

An approved response has `result_type: "query_result"` and includes `sql`, `columns`, `rows`, `row_count`, `plan`, `guardrails`, `hallucination_confidence`, and provider `metadata`. The deterministic demo returns `ORD-1003` and `ORD-1009`.

Known ambiguity returns options before generation:

```bash
curl -s http://localhost:8080/v1/query \
  -H 'content-type: application/json' \
  -d '{"question":"Show revenue by month"}'
```

The response distinguishes gross revenue before refunds from net revenue after succeeded refunds.

## Blocked request

The Compose fake demo has an intentional unsafe fixture:

```bash
docker compose exec -T backend python -m app.cli.full_stack_smoke
```

The fixture emits a `DELETE`; the API returns public `sql_validation_failed` and the statement is not executed. Raw provider errors, credentials, and stack traces are not exposed.

## Schema, history, and feedback

```bash
curl -s http://localhost:8080/v1/schema
curl -s 'http://localhost:8080/v1/history?limit=10'
curl -s http://localhost:8080/v1/feedback \
  -H 'content-type: application/json' \
  -d '{"request_id":"docs-safe-query","rating":"correct"}'
```

Schema output is limited to configured business metadata. History contains redacted audit metadata rather than raw result rows. Feedback ratings are `correct`, `incorrect`, or `unsure`.
