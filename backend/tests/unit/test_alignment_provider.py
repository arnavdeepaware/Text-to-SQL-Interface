from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.domain.query_execution import QueryResultColumn
from app.providers.alignment import (
    BackTranslationCredentialsUnavailableError,
    BackTranslationInput,
    BackTranslationMalformedOutputError,
    BackTranslationResult,
)
from app.providers.openai_alignment import OpenAIBackTranslationProvider


def test_openai_back_translation_fails_closed_without_credentials() -> None:
    provider = OpenAIBackTranslationProvider(
        Settings(environment="test", confidence_semantic_enabled=True, openai_api_key=None)
    )

    with pytest.raises(BackTranslationCredentialsUnavailableError, match="API key"):
        provider.back_translate(back_translation_input())


def test_openai_back_translation_validates_parsed_output_from_injected_client() -> None:
    client = FakeOpenAIClient(
        FakeOpenAIResponse(
            output_parsed=BackTranslationResult(
                question="How many orders are counted?",
                summary="Counts orders.",
                semantic_claims=["metric=order count"],
                referenced_tables=["commerce.orders"],
                referenced_columns=["commerce.orders.order_id"],
            ),
            usage=FakeUsage(input_tokens=10, output_tokens=6, total_tokens=16),
        )
    )
    provider = OpenAIBackTranslationProvider(
        Settings(
            environment="test",
            confidence_semantic_enabled=True,
            openai_api_key=SecretStr("test-key"),
        ),
        client=client,
    )

    draft = provider.back_translate(back_translation_input())

    assert draft.result.question == "How many orders are counted?"
    assert draft.telemetry.provider_name == "openai"
    assert draft.telemetry.input_tokens == 10
    assert client.responses.calls == 1
    assert client.responses.last_kwargs["text_format"] is BackTranslationResult
    messages = client.responses.last_kwargs["input"]
    assert isinstance(messages, list)
    prompt_text = "\n".join(str(message["content"]) for message in messages)
    assert "Executed SQL:" in prompt_text
    assert "Original question" not in prompt_text
    assert "Show gross revenue" not in prompt_text


def test_openai_back_translation_malformed_output_fails_safely() -> None:
    provider = OpenAIBackTranslationProvider(
        Settings(
            environment="test",
            confidence_semantic_enabled=True,
            openai_api_key=SecretStr("test-key"),
        ),
        client=FakeOpenAIClient(FakeOpenAIResponse(output_text='{"question": 1}')),
    )

    with pytest.raises(BackTranslationMalformedOutputError):
        provider.back_translate(back_translation_input())


def back_translation_input() -> BackTranslationInput:
    return BackTranslationInput(
        executed_sql="SELECT count(*) AS order_count FROM commerce.orders LIMIT 1000",
        columns=(QueryResultColumn("order_count", "20"),),
        referenced_tables=("commerce.orders",),
        referenced_columns=("commerce.orders.order_id",),
        functions=("count",),
        row_count=1,
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
        output_parsed: BackTranslationResult | None = None,
        output_text: str | None = None,
        usage: FakeUsage | None = None,
    ) -> None:
        self.output_parsed = output_parsed
        self.output_text = output_text
        self.usage = usage


class FakeResponses:
    def __init__(self, response: FakeOpenAIResponse) -> None:
        self._response = response
        self.calls = 0
        self.last_kwargs: dict[str, Any] = {}

    def parse(self, **kwargs: object) -> FakeOpenAIResponse:
        self.calls += 1
        self.last_kwargs = kwargs
        assert kwargs["temperature"] == 0
        return self._response


class FakeOpenAIClient:
    def __init__(self, response: FakeOpenAIResponse) -> None:
        self.responses = FakeResponses(response)
