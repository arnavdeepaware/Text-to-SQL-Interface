from __future__ import annotations

from dataclasses import dataclass

from app.providers.alignment import (
    BackTranslationCredentialsUnavailableError,
    BackTranslationDraft,
    BackTranslationInput,
    BackTranslationMalformedOutputError,
    BackTranslationProviderTimeoutError,
    BackTranslationProviderUnavailableError,
    BackTranslationRateLimitError,
    BackTranslationResult,
    BackTranslationTelemetry,
)


@dataclass(frozen=True)
class FakeBackTranslationProvider:
    """Deterministic back-translator for tests and local confidence orchestration."""

    mode: str = "success"
    result: BackTranslationResult | None = None
    provider_latency_ms: int = 3
    input_tokens: int | None = 44
    output_tokens: int | None = 22
    retry_count: int = 0

    def back_translate(self, request: BackTranslationInput) -> BackTranslationDraft:
        if self.mode == "timeout":
            raise BackTranslationProviderTimeoutError("fake back-translation timed out")
        if self.mode == "rate_limited":
            raise BackTranslationRateLimitError("fake back-translation rate limited")
        if self.mode == "credentials_unavailable":
            raise BackTranslationCredentialsUnavailableError("fake credentials unavailable")
        if self.mode == "unavailable":
            raise BackTranslationProviderUnavailableError("fake back-translation unavailable")
        if self.mode == "malformed":
            raise BackTranslationMalformedOutputError("fake malformed back-translation")
        if self.mode != "success":
            raise ValueError(f"Unsupported fake back-translation mode: {self.mode}")

        result = self.result or default_back_translation(request)
        return BackTranslationDraft(
            result=result,
            telemetry=BackTranslationTelemetry(
                provider_name="fake",
                model_name="fake-back-translator",
                provider_latency_ms=self.provider_latency_ms,
                input_tokens=self.input_tokens,
                output_tokens=self.output_tokens,
                total_tokens=token_total(self.input_tokens, self.output_tokens),
                retry_count=self.retry_count,
            ),
        )


def default_back_translation(request: BackTranslationInput) -> BackTranslationResult:
    table_text = ", ".join(request.referenced_tables) or "the validated query"
    column_text = ", ".join(column.name for column in request.columns) or "result columns"
    functions = set(request.functions)

    if "count" in functions:
        question = f"What count does the SQL compute from {table_text}?"
        summary = f"Counts rows or entities from {table_text} and returns {column_text}."
    elif {"sum", "avg", "min", "max"} & functions:
        question = f"What aggregate metrics does the SQL compute from {table_text}?"
        summary = f"Computes aggregate metrics from {table_text} and returns {column_text}."
    else:
        question = f"What records does the SQL return from {table_text}?"
        summary = f"Returns selected records from {table_text} with {column_text}."

    return BackTranslationResult(
        question=question,
        summary=summary,
        semantic_claims=[
            f"tables={table_text}",
            f"columns={column_text}",
            f"row_count={request.row_count}",
        ],
        referenced_tables=list(request.referenced_tables),
        referenced_columns=list(request.referenced_columns),
    )


def token_total(input_tokens: int | None, output_tokens: int | None) -> int | None:
    if input_tokens is None or output_tokens is None:
        return None
    return input_tokens + output_tokens
