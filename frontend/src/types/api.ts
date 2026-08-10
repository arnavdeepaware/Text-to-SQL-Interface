export interface APIErrorBody {
  error: {
    code: string;
    message: string;
    request_id: string;
  };
}

export interface HealthResponse {
  status: "ok" | "degraded";
  version: string;
  checks: Record<string, { status: "ok" | "unavailable" }>;
}

export interface QueryRequest {
  question: string;
  refresh_schema?: boolean;
}

export interface SQLGenerationTelemetry {
  provider_name: string;
  model_name: string;
  provider_latency_ms: number;
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  retry_count: number;
}

export interface SQLDraftMetadata {
  model_confidence: number;
  tables_used: string[];
  columns_used: string[];
  assumptions: string[];
  telemetry: SQLGenerationTelemetry;
}

export interface SQLDraftResponse {
  result_type: "sql_draft";
  request_id: string;
  question: string;
  sql: string;
  explanation: string;
  metadata: SQLDraftMetadata;
}

export interface ClarificationOption {
  interpretation: string;
  example: string;
}

export interface ClarificationRequiredResponse {
  result_type: "clarification_required";
  request_id: string;
  question: string;
  message: string;
  clarification_options: ClarificationOption[];
}

export interface QueryResultColumn {
  name: string;
  type_code: string | null;
}

export interface QueryPlanSummary {
  estimated_rows: number;
  total_cost: number;
  plan_nodes: string[];
  referenced_relations: string[];
}

export interface QueryExecutionMetadata {
  row_count: number;
  execution_duration_ms: number;
  truncated: boolean;
}

export interface GuardrailFinding {
  code: string;
  message: string;
  rule_name: string;
  severity: string;
}

export interface GuardrailMetadata {
  statement_type: string;
  effective_limit: number | null;
  limit_was_added: boolean;
  limit_was_reduced: boolean;
  subquery_depth: number;
  findings: GuardrailFinding[];
}

export interface ValidationSignal {
  code: string;
  status: string;
  score: number;
  explanation: string;
  evidence: Record<string, unknown>;
}

export interface ConfidenceComponent {
  name: string;
  status: string;
  score: number;
  weight: number;
  contribution: number;
  explanation: string;
  signal_codes: string[];
  evidence: Record<string, unknown>;
}

export interface HallucinationConfidence {
  status: "passed" | "failed" | "unavailable" | "not_applicable";
  score: number | null;
  confidence_band: "high" | "medium" | "low" | "blocked" | "not_applicable";
  signal_breakdown: ConfidenceComponent[];
  warnings: string[];
  rationale: string;
  signals: ValidationSignal[];
}

export interface QueryExecutionResponse {
  result_type: "query_result";
  request_id: string;
  question: string;
  sql: string;
  explanation: string;
  columns: QueryResultColumn[];
  rows: Record<string, unknown>[];
  row_count: number;
  execution_duration_ms: number;
  truncated: boolean;
  execution_metadata: QueryExecutionMetadata;
  plan: QueryPlanSummary;
  guardrails: GuardrailMetadata;
  hallucination_confidence: HallucinationConfidence;
  metadata: SQLDraftMetadata;
}

export type QueryResponse = QueryExecutionResponse | ClarificationRequiredResponse;

export interface ColumnSchema {
  name: string;
  sql_type: string;
  nullable: boolean;
  default: string | null;
  sample_values: string[];
}

export interface PrimaryKeySchema {
  columns: string[];
  name: string | null;
}

export interface ForeignKeySchema {
  name: string | null;
  source_schema: string;
  source_table: string;
  source_columns: string[];
  referred_schema: string;
  referred_table: string;
  referred_columns: string[];
  display_path: string;
}

export interface TableSchema {
  schema_name: string;
  name: string;
  identifier: string;
  columns: ColumnSchema[];
  primary_key: PrimaryKeySchema;
  foreign_keys: ForeignKeySchema[];
}

export interface GlossaryTerm {
  name: string;
  definition: string;
  expression: string;
  related_tables: string[];
  related_columns: string[];
}

export interface BusinessGlossary {
  version: number;
  terms: GlossaryTerm[];
}

export interface SchemaCache {
  generated_at: string;
  expires_at: string;
  ttl_seconds: number;
  refreshed: boolean;
}

export interface DatabaseSchemaResponse {
  schemas: string[];
  tables: TableSchema[];
  relationships: ForeignKeySchema[];
  glossary: BusinessGlossary;
  cache: SchemaCache;
}

export type FeedbackRating = "correct" | "incorrect" | "unsure";

export interface FeedbackRequest {
  request_id: string;
  rating: FeedbackRating;
  comment?: string | null;
}

export interface QueryFeedbackResponse {
  id: number;
  request_id: string;
  rating: FeedbackRating;
  comment: string | null;
  created_at: string;
}

export interface QueryHistoryRecord {
  id: number;
  request_id: string;
  normalized_question: string;
  generated_sql: string | null;
  outcome: "success" | "clarification_required" | "blocked" | "failed";
  blocked_reasons: string[];
  execution_metadata: Record<string, unknown>;
  confidence_breakdown: Record<string, unknown>;
  provider_metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  feedback: QueryFeedbackResponse[];
}

export interface QueryHistoryResponse {
  records: QueryHistoryRecord[];
  limit: number;
  offset: number;
  total: number;
  retention_policy: Record<string, number | string>;
  privacy_limitations: string[];
}
