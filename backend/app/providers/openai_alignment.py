from __future__ import annotations

import json
from time import perf_counter
from typing import Any

from pydantic import ValidationError

from app.core.config import Settings
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


class OpenAIBackTranslationProvider:
    """OpenAI SQL-to-question back-translator using strict structured output."""

    provider_name = "openai"

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self._settings = settings
        self._client = client

    def back_translate(self, request: BackTranslationInput) -> BackTranslationDraft:
        client = self._client or self._build_client()
        started = perf_counter()
        retry_count = 0

        for attempt in range(self._settings.confidence_alignment_max_retries + 1):
            try:
                return self._back_translate_once(client, request, started, retry_count)
            except (BackTranslationRateLimitError, BackTranslationProviderTimeoutError):
                if attempt >= self._settings.confidence_alignment_max_retries:
                    raise
                retry_count += 1

        raise BackTranslationProviderUnavailableError("Back-translation retry policy exhausted")

    def _build_client(self) -> Any:
        if self._settings.openai_api_key is None:
            raise BackTranslationCredentialsUnavailableError("OpenAI API key is not configured")

        try:
            from openai import OpenAI  # type: ignore[import-not-found]
        except ImportError as exc:
            raise BackTranslationCredentialsUnavailableError("OpenAI SDK is not installed") from exc

        return OpenAI(
            api_key=self._settings.openai_api_key.get_secret_value(),
            timeout=self._settings.confidence_alignment_timeout_seconds,
            max_retries=0,
        )

    def _back_translate_once(
        self,
        client: Any,
        request: BackTranslationInput,
        started: float,
        retry_count: int,
    ) -> BackTranslationDraft:
        messages = back_translation_messages(request)
        try:
            if hasattr(client.responses, "parse"):
                response = client.responses.parse(
                    model=self._settings.confidence_alignment_model,
                    input=messages,
                    text_format=BackTranslationResult,
                    max_output_tokens=self._settings.confidence_alignment_max_output_tokens,
                    temperature=0,
                )
                result = parsed_response_output(response)
            else:
                response = client.responses.create(
                    model=self._settings.confidence_alignment_model,
                    input=messages,
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": "BackTranslationResult",
                            "schema": BackTranslationResult.model_json_schema(),
                            "strict": True,
                        }
                    },
                    max_output_tokens=self._settings.confidence_alignment_max_output_tokens,
                    temperature=0,
                )
                result = BackTranslationResult.model_validate_json(response.output_text)
        except (
            BackTranslationCredentialsUnavailableError,
            BackTranslationMalformedOutputError,
            BackTranslationProviderTimeoutError,
            BackTranslationProviderUnavailableError,
            BackTranslationRateLimitError,
        ):
            raise
        except ValidationError as exc:
            raise BackTranslationMalformedOutputError(
                "OpenAI back-translation structured output validation failed"
            ) from exc
        except json.JSONDecodeError as exc:
            raise BackTranslationMalformedOutputError(
                "OpenAI back-translation returned invalid JSON"
            ) from exc
        except Exception as exc:
            raise mapped_openai_error(exc) from exc

        return BackTranslationDraft(
            result=result,
            telemetry=BackTranslationTelemetry(
                provider_name=self.provider_name,
                model_name=self._settings.confidence_alignment_model,
                provider_latency_ms=elapsed_ms(started),
                input_tokens=usage_value(response, "input_tokens", "prompt_tokens"),
                output_tokens=usage_value(response, "output_tokens", "completion_tokens"),
                total_tokens=usage_value(response, "total_tokens"),
                retry_count=retry_count,
            ),
        )


def back_translation_messages(request: BackTranslationInput) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": "\n".join(
                (
                    "You back-translate already-validated PostgreSQL into a "
                    "natural-language question.",
                    "You are not judging whether the SQL is correct.",
                    "You do not know the user's original question.",
                    "Use only the SQL facts in the user message.",
                    "Return strict structured output.",
                )
            ),
        },
        {
            "role": "user",
            "content": "\n".join(
                (
                    "Executed SQL:",
                    request.executed_sql,
                    "",
                    "Output columns:",
                    ", ".join(
                        f"{column.name}:{column.type_code or 'unknown'}"
                        for column in request.columns
                    )
                    or "none",
                    "",
                    "Referenced tables:",
                    ", ".join(request.referenced_tables) or "none",
                    "",
                    "Referenced columns:",
                    ", ".join(request.referenced_columns) or "none",
                    "",
                    "Aggregate/functions:",
                    ", ".join(request.functions) or "none",
                    "",
                    f"Returned row count: {request.row_count}",
                    f"Result truncated: {request.truncated}",
                )
            ),
        },
    ]


def parsed_response_output(response: Any) -> BackTranslationResult:
    parsed = getattr(response, "output_parsed", None)
    if isinstance(parsed, BackTranslationResult):
        return parsed

    output = getattr(response, "output", None)
    if isinstance(output, list):
        for item in output:
            content = getattr(item, "content", None)
            if not isinstance(content, list):
                continue
            for content_item in content:
                parsed_content = getattr(content_item, "parsed", None)
                if isinstance(parsed_content, BackTranslationResult):
                    return parsed_content

    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str):
        return BackTranslationResult.model_validate_json(output_text)

    raise BackTranslationMalformedOutputError(
        "OpenAI back-translation response did not contain parsed output"
    )


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
        return BackTranslationProviderTimeoutError("OpenAI back-translation timed out")
    if error_name == "RateLimitError":
        return BackTranslationRateLimitError("OpenAI back-translation was rate limited")
    if error_name in {"AuthenticationError", "PermissionDeniedError"}:
        return BackTranslationCredentialsUnavailableError(
            "OpenAI back-translation credentials were rejected"
        )
    if error_name in {"APIConnectionError", "InternalServerError", "APIStatusError"}:
        return BackTranslationProviderUnavailableError("OpenAI back-translation unavailable")
    return BackTranslationProviderUnavailableError("OpenAI back-translation failed")
