from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.domain.query_execution import QueryResultColumn


class BackTranslationProviderError(RuntimeError):
    """Base typed error for SQL-to-question provider failures."""

    public_code = "back_translation_provider_error"
    public_message = "SQL back-translation failed."


class BackTranslationMalformedOutputError(BackTranslationProviderError):
    public_code = "back_translation_malformed_output"
    public_message = "The back-translation provider returned malformed structured output."


class BackTranslationProviderTimeoutError(BackTranslationProviderError):
    public_code = "back_translation_provider_timeout"
    public_message = "The back-translation provider timed out."


class BackTranslationRateLimitError(BackTranslationProviderError):
    public_code = "back_translation_rate_limited"
    public_message = "The back-translation provider is rate limited."


class BackTranslationCredentialsUnavailableError(BackTranslationProviderError):
    public_code = "back_translation_credentials_unavailable"
    public_message = "Back-translation credentials are unavailable."


class BackTranslationProviderUnavailableError(BackTranslationProviderError):
    public_code = "back_translation_provider_unavailable"
    public_message = "The back-translation provider is unavailable."


class BackTranslationResult(BaseModel):
    """Strict public-safe semantic description of what validated SQL computes."""

    question: str = Field(min_length=1, max_length=500)
    summary: str = Field(min_length=1, max_length=1_000)
    semantic_claims: list[str] = Field(default_factory=list, max_length=12)
    referenced_tables: list[str] = Field(default_factory=list, max_length=50)
    referenced_columns: list[str] = Field(default_factory=list, max_length=100)

    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class BackTranslationInput:
    """Provider input restricted to executed SQL facts, never original intent."""

    executed_sql: str
    columns: tuple[QueryResultColumn, ...]
    referenced_tables: tuple[str, ...]
    referenced_columns: tuple[str, ...]
    functions: tuple[str, ...]
    row_count: int
    truncated: bool


@dataclass(frozen=True)
class BackTranslationTelemetry:
    """Non-secret provider telemetry for a SQL back-translation attempt."""

    provider_name: str
    model_name: str
    provider_latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    retry_count: int = 0


@dataclass(frozen=True)
class BackTranslationDraft:
    """Back-translation result plus provider telemetry."""

    result: BackTranslationResult
    telemetry: BackTranslationTelemetry


class SQLBackTranslator(Protocol):
    """Provider-neutral SQL-to-question back-translator."""

    def back_translate(self, request: BackTranslationInput) -> BackTranslationDraft: ...
