import { http, HttpResponse } from "msw";

import type {
  DatabaseSchemaResponse,
  HealthResponse,
  QueryFeedbackResponse,
  QueryHistoryResponse,
  QueryExecutionResponse,
  QueryResponse
} from "../../types/api";

export const mockHealth: HealthResponse = {
  status: "ok",
  version: "0.1.0",
  checks: {
    database: { status: "ok" }
  }
};

export const mockQueryExecutionResponse: QueryExecutionResponse = {
  result_type: "query_result",
  request_id: "req-test-query",
  question: "Show gross revenue by product category",
  sql: "SELECT categories.name AS category_name, SUM(order_items.line_total_cents) AS gross_revenue_cents FROM commerce.order_items JOIN commerce.products ON order_items.product_id = products.product_id JOIN commerce.categories ON products.category_id = categories.category_id GROUP BY categories.name ORDER BY category_name",
  explanation: "Aggregates line totals by product category from the read-only commerce schema.",
  columns: [
    { name: "category_name", type_code: "text" },
    { name: "gross_revenue_cents", type_code: "int8" }
  ],
  rows: [
    { category_name: "Hardware", gross_revenue_cents: 52500 },
    { category_name: "Books", gross_revenue_cents: 21000 }
  ],
  row_count: 2,
  execution_duration_ms: 18,
  truncated: false,
  execution_metadata: {
    row_count: 2,
    execution_duration_ms: 18,
    truncated: false
  },
  plan: {
    estimated_rows: 2,
    total_cost: 10.2,
    plan_nodes: ["Aggregate", "Hash Join"],
    referenced_relations: ["commerce.order_items", "commerce.products", "commerce.categories"]
  },
  guardrails: {
    statement_type: "select",
    effective_limit: 100,
    limit_was_added: true,
    limit_was_reduced: false,
    subquery_depth: 0,
    findings: []
  },
  hallucination_confidence: {
    status: "passed",
    score: 0.91,
    confidence_band: "high",
    signal_breakdown: [],
    warnings: [],
    rationale: "Validation signals passed.",
    signals: []
  },
  metadata: {
    model_confidence: 0.72,
    tables_used: ["commerce.order_items", "commerce.products", "commerce.categories"],
    columns_used: ["commerce.categories.name", "commerce.order_items.line_total_cents"],
    assumptions: [],
    telemetry: {
      provider_name: "fake",
      model_name: "fake-sql-generator",
      provider_latency_ms: 7,
      input_tokens: 100,
      output_tokens: 25,
      total_tokens: 125,
      retry_count: 0
    }
  }
};

export const mockQueryResponse: QueryResponse = mockQueryExecutionResponse;

export const mockSchemaResponse: DatabaseSchemaResponse = {
  schemas: ["commerce"],
  tables: [
    {
      schema_name: "commerce",
      name: "orders",
      identifier: "commerce.orders",
      columns: [
        {
          name: "id",
          sql_type: "integer",
          nullable: false,
          default: null,
          sample_values: []
        }
      ],
      primary_key: { columns: ["id"], name: "orders_pkey" },
      foreign_keys: []
    }
  ],
  relationships: [],
  glossary: { version: 1, terms: [] },
  cache: {
    generated_at: "2026-08-10T00:00:00Z",
    expires_at: "2026-08-10T00:05:00Z",
    ttl_seconds: 300,
    refreshed: false
  }
};

export const mockHistoryResponse: QueryHistoryResponse = {
  records: [],
  limit: 25,
  offset: 0,
  total: 0,
  retention_policy: {
    status: "placeholder",
    query_history_retention_days: 30,
    query_feedback_retention_days: 90
  },
  privacy_limitations: ["Raw result rows are not stored."]
};

export const mockFeedbackResponse: QueryFeedbackResponse = {
  id: 1,
  request_id: "req-test-query",
  rating: "correct",
  comment: null,
  created_at: "2026-08-10T00:00:00Z"
};

export const handlers = [
  http.get("*/health", () => HttpResponse.json(mockHealth)),
  http.post("*/v1/query", () => HttpResponse.json(mockQueryResponse)),
  http.get("*/v1/schema", () => HttpResponse.json(mockSchemaResponse)),
  http.get("*/v1/history", () => HttpResponse.json(mockHistoryResponse)),
  http.post("*/v1/feedback", () => HttpResponse.json(mockFeedbackResponse, { status: 201 }))
];
