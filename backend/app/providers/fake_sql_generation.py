from dataclasses import dataclass

from app.domain.prompt import SQLGenerationPrompt
from app.domain.sql_generation import (
    SQLGenerationDraft,
    SQLGenerationResult,
    SQLGenerationTelemetry,
)
from app.providers.sql_generation import (
    SQLGenerationCredentialsUnavailableError,
    SQLGenerationMalformedOutputError,
    SQLGenerationProviderTimeoutError,
    SQLGenerationProviderUnavailableError,
    SQLGenerationRateLimitError,
)


@dataclass(frozen=True)
class FakeSQLGenerator:
    """Deterministic SQL generator for tests and local orchestration."""

    mode: str = "success"
    result: SQLGenerationResult | None = None
    provider_latency_ms: int = 7
    input_tokens: int | None = 111
    output_tokens: int | None = 33
    retry_count: int = 0
    profile: str = "placeholder"

    def generate(self, prompt: SQLGenerationPrompt) -> SQLGenerationDraft:
        if self.mode == "timeout":
            raise SQLGenerationProviderTimeoutError("fake provider timed out")
        if self.mode == "rate_limited":
            raise SQLGenerationRateLimitError("fake provider rate limited")
        if self.mode == "credentials_unavailable":
            raise SQLGenerationCredentialsUnavailableError("fake credentials unavailable")
        if self.mode == "unavailable":
            raise SQLGenerationProviderUnavailableError("fake provider unavailable")
        if self.mode == "malformed":
            raise SQLGenerationMalformedOutputError("fake malformed output")
        if self.mode != "success":
            raise ValueError(f"Unsupported fake SQL generation mode: {self.mode}")

        result = self.result or default_fake_result(prompt, profile=self.profile)
        return SQLGenerationDraft(
            result=result,
            telemetry=SQLGenerationTelemetry(
                provider_name="fake",
                model_name="fake-sql-generator",
                provider_latency_ms=self.provider_latency_ms,
                input_tokens=self.input_tokens,
                output_tokens=self.output_tokens,
                total_tokens=token_total(self.input_tokens, self.output_tokens),
                retry_count=self.retry_count,
            ),
        )


def default_fake_result(
    prompt: SQLGenerationPrompt,
    profile: str = "placeholder",
) -> SQLGenerationResult:
    if profile == "demo":
        return demo_fake_result(prompt) or placeholder_fake_result(prompt)
    if profile != "placeholder":
        raise ValueError(f"Unsupported fake SQL generation profile: {profile}")
    return placeholder_fake_result(prompt)


def placeholder_fake_result(prompt: SQLGenerationPrompt) -> SQLGenerationResult:
    return SQLGenerationResult(
        sql="SELECT 1 AS generated_sql_placeholder;",
        explanation=f"Fake SQL draft for: {prompt.original_question}",
        model_confidence=0.75,
        tables_used=[],
        columns_used=[],
        assumptions=[],
        clarification_needed=False,
        clarification_options=[],
    )


def demo_fake_result(prompt: SQLGenerationPrompt) -> SQLGenerationResult | None:
    question = " ".join(prompt.original_question.casefold().split())
    if question == "list cancelled orders for the demo smoke test":
        return SQLGenerationResult(
            sql=(
                "SELECT order_number, status FROM commerce.orders "
                "WHERE status = 'cancelled' ORDER BY order_number;"
            ),
            explanation="Lists the seeded cancelled orders for the deterministic smoke test.",
            model_confidence=0.99,
            tables_used=["commerce.orders"],
            columns_used=["commerce.orders.order_number", "commerce.orders.status"],
            assumptions=[],
            clarification_needed=False,
            clarification_options=[],
        )
    if question == "show cancelled orders for the unsafe smoke test":
        return SQLGenerationResult(
            sql="DELETE FROM commerce.orders WHERE status = 'cancelled';",
            explanation="Intentional unsafe fixture; guardrails must reject it.",
            model_confidence=0.99,
            tables_used=["commerce.orders"],
            columns_used=["commerce.orders.status"],
            assumptions=[],
            clarification_needed=False,
            clarification_options=[],
        )
    return None


def token_total(input_tokens: int | None, output_tokens: int | None) -> int | None:
    if input_tokens is None or output_tokens is None:
        return None
    return input_tokens + output_tokens
