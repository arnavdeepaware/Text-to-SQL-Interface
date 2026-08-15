import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.domain.prompt import PromptMessage, SQLGenerationPrompt
from app.domain.sql_generation import SQLGenerationResult
from app.providers.fake_sql_generation import FakeSQLGenerator
from app.providers.openai_sql_generation import OpenAISQLGenerator
from app.providers.sql_generation import (
    SQLGenerationCredentialsUnavailableError,
    SQLGenerationMalformedOutputError,
    SQLGenerationProviderTimeoutError,
    SQLGenerationProviderUnavailableError,
    SQLGenerationRateLimitError,
)


def test_valid_structured_output_is_accepted_by_fake_generator() -> None:
    result = SQLGenerationResult(
        sql="SELECT count(*) FROM commerce.orders;",
        explanation="Counts orders.",
        model_confidence=0.82,
        tables_used=["commerce.orders"],
        columns_used=[],
        assumptions=[],
        clarification_needed=False,
        clarification_options=[],
    )

    draft = FakeSQLGenerator(result=result).generate(fake_prompt())

    assert draft.result == result
    assert draft.telemetry.provider_name == "fake"
    assert draft.telemetry.model_name == "fake-sql-generator"
    assert draft.telemetry.provider_latency_ms == 7
    assert draft.telemetry.input_tokens == 111
    assert draft.telemetry.output_tokens == 33
    assert draft.telemetry.total_tokens == 144


def test_invalid_structured_output_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        SQLGenerationResult.model_validate(
            {
                "sql": "SELECT 1;",
                "explanation": "ok",
                "model_confidence": 0.5,
                "tables_used": [],
                "columns_used": [],
                "assumptions": [],
                "clarification_needed": False,
                "clarification_options": [],
                "unexpected": "nope",
            }
        )


def test_invalid_structured_output_requires_sql_without_clarification() -> None:
    with pytest.raises(ValidationError, match="sql is required"):
        SQLGenerationResult(
            sql=None,
            explanation="No SQL.",
            model_confidence=0.5,
            tables_used=[],
            columns_used=[],
            assumptions=[],
            clarification_needed=False,
            clarification_options=[],
        )


def test_clarification_output_requires_options_and_no_sql() -> None:
    with pytest.raises(ValidationError, match="clarification options"):
        SQLGenerationResult(
            sql=None,
            explanation="Ambiguous.",
            model_confidence=0.2,
            tables_used=[],
            columns_used=[],
            assumptions=[],
            clarification_needed=True,
            clarification_options=[],
        )

    result = SQLGenerationResult(
        sql=None,
        explanation="Ambiguous.",
        model_confidence=0.2,
        tables_used=[],
        columns_used=[],
        assumptions=[],
        clarification_needed=True,
        clarification_options=["Gross revenue", "Net revenue"],
    )
    assert result.clarification_needed is True


@pytest.mark.parametrize(
    ("mode", "expected_error"),
    [
        ("malformed", SQLGenerationMalformedOutputError),
        ("timeout", SQLGenerationProviderTimeoutError),
        ("rate_limited", SQLGenerationRateLimitError),
        ("credentials_unavailable", SQLGenerationCredentialsUnavailableError),
        ("unavailable", SQLGenerationProviderUnavailableError),
    ],
)
def test_fake_generator_failures_are_typed(mode: str, expected_error: type[Exception]) -> None:
    with pytest.raises(expected_error):
        FakeSQLGenerator(mode=mode).generate(fake_prompt())


def test_demo_fake_generator_returns_safe_and_unsafe_smoke_fixtures() -> None:
    safe = FakeSQLGenerator(profile="demo").generate(
        fake_prompt("List cancelled orders for the demo smoke test")
    )
    unsafe = FakeSQLGenerator(profile="demo").generate(
        fake_prompt("Show cancelled orders for the unsafe smoke test")
    )

    assert safe.result.sql is not None
    assert safe.result.sql.startswith("SELECT order_number, status")
    assert unsafe.result.sql == "DELETE FROM commerce.orders WHERE status = 'cancelled';"


def test_openai_generator_fails_closed_without_credentials() -> None:
    generator = OpenAISQLGenerator(Settings(environment="test", openai_api_key=None))

    with pytest.raises(SQLGenerationCredentialsUnavailableError, match="API key"):
        generator.generate(fake_prompt())


def test_openai_generator_fails_closed_when_sdk_is_missing() -> None:
    generator = OpenAISQLGenerator(
        Settings(environment="test", openai_api_key=SecretStr("test-key")),
    )

    with pytest.raises(SQLGenerationCredentialsUnavailableError, match="SDK"):
        generator.generate(fake_prompt())


def test_openai_generator_validates_parsed_output_from_injected_client() -> None:
    client = FakeOpenAIClient(
        FakeOpenAIResponse(
            output_parsed=SQLGenerationResult(
                sql="SELECT count(*) FROM commerce.orders;",
                explanation="Counts orders.",
                model_confidence=0.9,
                tables_used=["commerce.orders"],
                columns_used=[],
                assumptions=[],
                clarification_needed=False,
                clarification_options=[],
            ),
            usage=FakeUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        )
    )
    generator = OpenAISQLGenerator(Settings(environment="test"), client=client)

    draft = generator.generate(fake_prompt())

    assert draft.result.sql == "SELECT count(*) FROM commerce.orders;"
    assert draft.telemetry.provider_name == "openai"
    assert draft.telemetry.model_name == "gpt-4.1-mini"
    assert draft.telemetry.input_tokens == 10
    assert draft.telemetry.output_tokens == 5
    assert draft.telemetry.total_tokens == 15
    assert client.responses.calls == 1


def test_openai_generator_retries_rate_limit_but_not_indefinitely() -> None:
    client = FakeOpenAIClient(
        FakeOpenAIResponse(
            output_parsed=SQLGenerationResult(
                sql="SELECT 1;",
                explanation="ok",
                model_confidence=0.6,
                tables_used=[],
                columns_used=[],
                assumptions=[],
                clarification_needed=False,
                clarification_options=[],
            )
        ),
        failures=(FakeRateLimitError(),),
    )
    generator = OpenAISQLGenerator(
        Settings(environment="test", sql_generation_max_retries=1),
        client=client,
    )

    draft = generator.generate(fake_prompt())

    assert draft.result.sql == "SELECT 1;"
    assert draft.telemetry.retry_count == 1
    assert client.responses.calls == 2


def test_openai_generator_malformed_output_fails_safely_without_retry() -> None:
    client = FakeOpenAIClient(FakeOpenAIResponse(output_text='{"sql": 1}'))
    generator = OpenAISQLGenerator(
        Settings(environment="test", sql_generation_max_retries=1),
        client=client,
    )

    with pytest.raises(SQLGenerationMalformedOutputError):
        generator.generate(fake_prompt())

    assert client.responses.calls == 1


def fake_prompt(question: str = "How many orders?") -> SQLGenerationPrompt:
    return SQLGenerationPrompt(
        original_question=question,
        sql_dialect="PostgreSQL",
        messages=(
            PromptMessage("system", "Return structured SQL."),
            PromptMessage("user", question),
        ),
        selected_few_shot_ids=(),
        context_budget_chars=1000,
        context_chars=100,
        truncated=False,
    )


class FakeUsage:
    def __init__(
        self,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        total_tokens: int | None = None,
    ) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.total_tokens = total_tokens


class FakeOpenAIResponse:
    def __init__(
        self,
        output_parsed: SQLGenerationResult | None = None,
        output_text: str | None = None,
        usage: FakeUsage | None = None,
    ) -> None:
        self.output_parsed = output_parsed
        self.output_text = output_text
        self.usage = usage


class FakeRateLimitError(Exception):
    pass


FakeRateLimitError.__name__ = "RateLimitError"


class FakeResponses:
    def __init__(
        self,
        response: FakeOpenAIResponse,
        failures: tuple[Exception, ...] = (),
    ) -> None:
        self._response = response
        self._failures = list(failures)
        self.calls = 0

    def parse(self, **kwargs: object) -> FakeOpenAIResponse:
        self.calls += 1
        if self._failures:
            raise self._failures.pop(0)
        assert kwargs["text_format"] is SQLGenerationResult
        assert kwargs["temperature"] == 0
        return self._response


class FakeOpenAIClient:
    def __init__(
        self,
        response: FakeOpenAIResponse,
        failures: tuple[Exception, ...] = (),
    ) -> None:
        self.responses = FakeResponses(response, failures)
