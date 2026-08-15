from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    app_name: str = "Text-to-SQL Interface"
    app_version: str = "0.1.0"
    environment: Literal["local", "test", "development", "staging", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_host: str = "127.0.0.1"
    database_port: int = Field(default=5432, ge=1, le=65535)
    database_name: str = "text_to_sql"
    database_user: str = "text_to_sql_reader"
    database_password: SecretStr = SecretStr("text_to_sql_reader_local_password")
    database_connect_timeout_seconds: int = Field(default=2, ge=1, le=30)
    database_statement_timeout_ms: int = Field(default=5_000, ge=100, le=60_000)
    database_pool_size: int = Field(default=5, ge=1, le=20)
    database_max_overflow: int = Field(default=0, ge=0, le=20)
    audit_database_user: str = "text_to_sql_audit_writer"
    audit_database_password: SecretStr = SecretStr("text_to_sql_audit_writer_local_password")
    query_history_enabled: bool = True
    query_history_default_limit: int = Field(default=25, ge=1, le=100)
    query_history_max_limit: int = Field(default=100, ge=1, le=500)
    query_feedback_comment_max_chars: int = Field(default=500, ge=0, le=2_000)
    query_history_retention_days: int = Field(default=30, ge=1, le=3650)
    query_feedback_retention_days: int = Field(default=90, ge=1, le=3650)
    schema_introspection_schemas: tuple[str, ...] = ("commerce",)
    schema_cache_ttl_seconds: int = Field(default=300, ge=0, le=86_400)
    schema_sample_limit: int = Field(default=20, ge=0, le=100)
    schema_sample_timeout_ms: int = Field(default=1_000, ge=100, le=10_000)
    schema_sample_columns: tuple[str, ...] = (
        "commerce.customers.region",
        "commerce.customers.country_code",
        "commerce.orders.status",
        "commerce.orders.billing_region",
        "commerce.orders.currency",
        "commerce.payments.payment_method",
        "commerce.payments.status",
        "commerce.refunds.status",
        "commerce.refunds.reason",
        "commerce.shipments.carrier",
        "commerce.shipments.status",
    )
    schema_retrieval_min_table_score: float = Field(default=8.0, ge=0.0, le=1_000.0)
    schema_retrieval_min_column_score: float = Field(default=4.0, ge=0.0, le=1_000.0)
    schema_retrieval_max_tables: int = Field(default=6, ge=1, le=50)
    schema_retrieval_max_columns_per_table: int = Field(default=12, ge=1, le=200)
    schema_retrieval_max_bridge_hops: int = Field(default=4, ge=0, le=10)
    schema_retrieval_use_embeddings: bool = False
    schema_retrieval_embedding_weight: float = Field(default=20.0, ge=0.0, le=100.0)
    prompt_sql_dialect: str = "PostgreSQL"
    prompt_context_budget_chars: int = Field(default=12_000, ge=500, le=100_000)
    prompt_max_few_shot_examples: int = Field(default=3, ge=0, le=8)
    sql_generation_model: str = "gpt-4.1-mini"
    sql_generation_provider: Literal["openai", "fake"] = "openai"
    sql_generation_fake_profile: Literal["placeholder", "demo"] = "placeholder"
    sql_generation_timeout_seconds: float = Field(default=20.0, ge=1.0, le=120.0)
    sql_generation_max_retries: int = Field(default=1, ge=0, le=3)
    sql_generation_max_output_tokens: int = Field(default=1_000, ge=100, le=8_000)
    sql_guardrail_max_subquery_depth: int = Field(default=3, ge=0, le=20)
    sql_guardrail_max_returned_rows: int = Field(default=1_000, ge=1, le=10_000)
    sql_guardrail_explain_timeout_ms: int = Field(default=1_000, ge=100, le=10_000)
    sql_guardrail_max_plan_rows: int = Field(default=50_000, ge=0, le=10_000_000)
    sql_guardrail_max_plan_total_cost: float = Field(default=100_000.0, ge=0.0)
    sql_execution_max_rows: int = Field(default=1_000, ge=1, le=10_000)
    sql_execution_lock_timeout_ms: int = Field(default=500, ge=50, le=10_000)
    deterministic_validation_enabled: bool = True
    result_sanity_null_heavy_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    result_sanity_min_percentage: float = Field(default=0.0)
    result_sanity_max_percentage: float = Field(default=100.0)
    result_sanity_min_date: str = "2020-01-01"
    result_sanity_max_date: str = "2030-12-31"
    confidence_semantic_enabled: bool = False
    confidence_alignment_provider: Literal["openai", "fake"] = "openai"
    confidence_alignment_model: str = "gpt-4.1-mini"
    confidence_alignment_timeout_seconds: float = Field(default=3.0, ge=0.1, le=30.0)
    confidence_alignment_max_retries: int = Field(default=0, ge=0, le=2)
    confidence_alignment_max_output_tokens: int = Field(default=300, ge=50, le=2_000)
    confidence_alignment_pass_threshold: float = Field(default=0.82, ge=0.0, le=1.0)
    confidence_alignment_fail_threshold: float = Field(default=0.55, ge=0.0, le=1.0)
    confidence_alignment_lexical_score_cap: float = Field(default=0.65, ge=0.0, le=1.0)
    confidence_multi_query_enabled: bool = False
    confidence_multi_query_timeout_seconds: float = Field(default=10.0, ge=0.1, le=60.0)
    confidence_multi_query_max_retries: int = Field(default=0, ge=0, le=2)
    confidence_multi_query_max_alternates: int = Field(default=1, ge=0, le=1)
    confidence_multi_query_max_result_rows: int = Field(default=100, ge=1, le=10_000)
    confidence_multi_query_max_execution_ms: int = Field(default=5_000, ge=100, le=60_000)
    confidence_multi_query_decimal_abs_tol: float = Field(default=0.000001, ge=0.0, le=1.0)
    confidence_multi_query_float_rel_tol: float = Field(default=1e-6, ge=0.0, le=1.0)
    confidence_multi_query_float_abs_tol: float = Field(default=1e-9, ge=0.0, le=1.0)
    confidence_weight_sql_syntax: float = Field(default=0.10, ge=0.0, le=1.0)
    confidence_weight_guardrail_approval: float = Field(default=0.15, ge=0.0, le=1.0)
    confidence_weight_schema_coverage: float = Field(default=0.20, ge=0.0, le=1.0)
    confidence_weight_result_sanity: float = Field(default=0.20, ge=0.0, le=1.0)
    confidence_weight_semantic_alignment: float = Field(default=0.15, ge=0.0, le=1.0)
    confidence_weight_multi_query_agreement: float = Field(default=0.18, ge=0.0, le=1.0)
    confidence_weight_model_reported: float = Field(default=0.02, ge=0.0, le=0.05)
    confidence_unavailable_score: float = Field(default=0.35, ge=0.0, le=1.0)
    confidence_not_applicable_score: float = Field(default=0.35, ge=0.0, le=1.0)
    confidence_high_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    confidence_medium_threshold: float = Field(default=0.70, ge=0.0, le=1.0)
    confidence_low_threshold: float = Field(default=0.50, ge=0.0, le=1.0)
    confidence_blocked_threshold: float = Field(default=0.35, ge=0.0, le=1.0)
    query_max_question_chars: int = Field(default=1_000, ge=1, le=10_000)
    openai_api_key: SecretStr | None = None
    openai_embedding_model: str = "text-embedding-3-small"
    openai_timeout_seconds: float = Field(default=10.0, ge=0.5, le=60.0)

    model_config = SettingsConfigDict(
        env_prefix="TEXT_TO_SQL_",
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_confidence_settings(self) -> "Settings":
        thresholds = (
            self.confidence_high_threshold,
            self.confidence_medium_threshold,
            self.confidence_low_threshold,
            self.confidence_blocked_threshold,
        )
        if not (
            thresholds[0] > thresholds[1] > thresholds[2] > thresholds[3]
        ):
            raise ValueError(
                "confidence thresholds must be ordered high > medium > low > blocked"
            )
        weight_total = sum(confidence_weights(self).values())
        if weight_total <= 0:
            raise ValueError("at least one confidence scoring weight must be positive")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


def confidence_weights(settings: Settings) -> dict[str, float]:
    return {
        "sql_syntax_validity": settings.confidence_weight_sql_syntax,
        "guardrail_approval": settings.confidence_weight_guardrail_approval,
        "schema_coverage": settings.confidence_weight_schema_coverage,
        "result_sanity": settings.confidence_weight_result_sanity,
        "semantic_alignment": settings.confidence_weight_semantic_alignment,
        "multi_query_agreement": settings.confidence_weight_multi_query_agreement,
        "model_reported_confidence": settings.confidence_weight_model_reported,
    }
