from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SQLGenerationResult(BaseModel):
    """Strict structured SQL draft returned by a provider."""

    sql: str | None
    explanation: str
    model_confidence: float = Field(ge=0.0, le=1.0)
    tables_used: list[str]
    columns_used: list[str]
    assumptions: list[str]
    clarification_needed: bool
    clarification_options: list[str]

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_sql_or_clarification(self) -> "SQLGenerationResult":
        if self.clarification_needed:
            if self.sql is not None:
                raise ValueError("sql must be null when clarification is needed")
            if not self.clarification_options:
                raise ValueError("clarification options are required when clarification is needed")
        elif not self.sql:
            raise ValueError("sql is required when clarification is not needed")
        return self


@dataclass(frozen=True)
class SQLGenerationTelemetry:
    """Non-secret provider telemetry for a SQL draft attempt."""

    provider_name: str
    model_name: str
    provider_latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    retry_count: int = 0


@dataclass(frozen=True)
class SQLGenerationDraft:
    """Validated SQL generation draft plus provider telemetry."""

    result: SQLGenerationResult
    telemetry: SQLGenerationTelemetry
