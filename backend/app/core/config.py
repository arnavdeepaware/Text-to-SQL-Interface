from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
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
    query_max_question_chars: int = Field(default=1_000, ge=1, le=10_000)
    openai_api_key: SecretStr | None = None
    openai_embedding_model: str = "text-embedding-3-small"
    openai_timeout_seconds: float = Field(default=10.0, ge=0.5, le=60.0)

    model_config = SettingsConfigDict(
        env_prefix="TEXT_TO_SQL_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
