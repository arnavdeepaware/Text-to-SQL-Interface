from __future__ import annotations

import json
from time import perf_counter
from typing import Any

from pydantic import ValidationError

from app.core.config import Settings
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


class OpenAISQLGenerator:
    """OpenAI SQL generator using strict structured outputs when the SDK is installed."""

    provider_name = "openai"

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self._settings = settings
        self._client = client

    def generate(self, prompt: SQLGenerationPrompt) -> SQLGenerationDraft:
        client = self._client or self._build_client()
        retry_count = 0
        started = perf_counter()

        for attempt in range(self._settings.sql_generation_max_retries + 1):
            try:
                draft = self._generate_once(client, prompt, started, retry_count)
            except SQLGenerationRateLimitError:
                if attempt >= self._settings.sql_generation_max_retries:
                    raise
                retry_count += 1
                continue
            except SQLGenerationProviderTimeoutError:
                if attempt >= self._settings.sql_generation_max_retries:
                    raise
                retry_count += 1
                continue
            else:
                return draft

        raise SQLGenerationProviderUnavailableError("SQL generation retry policy was exhausted")

    def _build_client(self) -> Any:
        if self._settings.openai_api_key is None:
            raise SQLGenerationCredentialsUnavailableError("OpenAI API key is not configured")

        try:
            from openai import OpenAI  # type: ignore[import-not-found]
        except ImportError as exc:
            raise SQLGenerationCredentialsUnavailableError("OpenAI SDK is not installed") from exc

        return OpenAI(
            api_key=self._settings.openai_api_key.get_secret_value(),
            timeout=self._settings.sql_generation_timeout_seconds,
            max_retries=0,
        )

    def _generate_once(
        self,
        client: Any,
        prompt: SQLGenerationPrompt,
        started: float,
        retry_count: int,
    ) -> SQLGenerationDraft:
        messages = [
            {"role": message.role, "content": message.content}
            for message in prompt.messages
        ]

        try:
            if hasattr(client.responses, "parse"):
                response = client.responses.parse(
                    model=self._settings.sql_generation_model,
                    input=messages,
                    text_format=SQLGenerationResult,
                    max_output_tokens=self._settings.sql_generation_max_output_tokens,
                    temperature=0,
                )
                result = parsed_response_output(response)
            else:
                response = client.responses.create(
                    model=self._settings.sql_generation_model,
                    input=messages,
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": "SQLGenerationResult",
                            "schema": SQLGenerationResult.model_json_schema(),
                            "strict": True,
                        }
                    },
                    max_output_tokens=self._settings.sql_generation_max_output_tokens,
                    temperature=0,
                )
                result = SQLGenerationResult.model_validate_json(response.output_text)
        except ValidationError as exc:
            raise SQLGenerationMalformedOutputError("OpenAI structured output validation failed") from exc
        except json.JSONDecodeError as exc:
            raise SQLGenerationMalformedOutputError("OpenAI returned invalid JSON") from exc
        except Exception as exc:
            raise mapped_openai_error(exc) from exc

        return SQLGenerationDraft(
            result=result,
            telemetry=SQLGenerationTelemetry(
                provider_name=self.provider_name,
                model_name=self._settings.sql_generation_model,
                provider_latency_ms=elapsed_ms(started),
                input_tokens=usage_value(response, "input_tokens", "prompt_tokens"),
                output_tokens=usage_value(response, "output_tokens", "completion_tokens"),
                total_tokens=usage_value(response, "total_tokens"),
                retry_count=retry_count,
            ),
        )


def parsed_response_output(response: Any) -> SQLGenerationResult:
    parsed = getattr(response, "output_parsed", None)
    if isinstance(parsed, SQLGenerationResult):
        return parsed

    output = getattr(response, "output", None)
    if isinstance(output, list):
        for item in output:
            content = getattr(item, "content", None)
            if not isinstance(content, list):
                continue
            for content_item in content:
                parsed_content = getattr(content_item, "parsed", None)
                if isinstance(parsed_content, SQLGenerationResult):
                    return parsed_content

    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str):
        return SQLGenerationResult.model_validate_json(output_text)

    raise SQLGenerationMalformedOutputError("OpenAI response did not contain parsed output")


def usage_value(response: Any, *names: str) -> int | None:
    usage = getattr(response, "usage", None)
    for name in names:
        value = getattr(usage, name, None)
        if isinstance(value, int):
            return value
    return None


def elapsed_ms(started: float) -> int:
    return max(0, round((perf_counter() - started) * 1000))


def mapped_openai_error(exc: Exception) -> Exception:
    error_name = type(exc).__name__
    if error_name in {"APITimeoutError", "Timeout", "TimeoutError"}:
        return SQLGenerationProviderTimeoutError("OpenAI SQL generation timed out")
    if error_name == "RateLimitError":
        return SQLGenerationRateLimitError("OpenAI SQL generation was rate limited")
    if error_name in {"AuthenticationError", "PermissionDeniedError"}:
        return SQLGenerationCredentialsUnavailableError("OpenAI credentials were rejected")
    if error_name in {"APIConnectionError", "InternalServerError", "APIStatusError"}:
        return SQLGenerationProviderUnavailableError("OpenAI SQL generation unavailable")
    return SQLGenerationProviderUnavailableError("OpenAI SQL generation failed")
