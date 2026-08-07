from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol
from urllib import request
from urllib.error import URLError

from app.core.config import Settings


class EmbeddingProviderError(RuntimeError):
    """Raised when an embedding provider cannot return usable vectors."""


class EmbeddingProvider(Protocol):
    """Provider-neutral embedding boundary for retrieval services."""

    @property
    def is_configured(self) -> bool: ...

    def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]: ...


@dataclass(frozen=True)
class OpenAIEmbeddingProvider:
    """Minimal OpenAI embeddings adapter disabled when no API key is configured."""

    settings: Settings

    @property
    def is_configured(self) -> bool:
        return self.settings.openai_api_key is not None

    def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        if not self.is_configured:
            raise EmbeddingProviderError("OpenAI embeddings are not configured")
        if not texts:
            return ()

        api_key = self.settings.openai_api_key
        if api_key is None:
            raise EmbeddingProviderError("OpenAI embeddings are not configured")

        payload = json.dumps(
            {
                "model": self.settings.openai_embedding_model,
                "input": list(texts),
            }
        ).encode("utf-8")
        http_request = request.Request(
            "https://api.openai.com/v1/embeddings",
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key.get_secret_value()}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with request.urlopen(
                http_request,
                timeout=self.settings.openai_timeout_seconds,
            ) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (OSError, URLError, json.JSONDecodeError) as exc:
            raise EmbeddingProviderError("OpenAI embeddings request failed") from exc

        try:
            rows = sorted(body["data"], key=lambda item: int(item["index"]))
            vectors = tuple(tuple(float(value) for value in item["embedding"]) for item in rows)
        except (KeyError, TypeError, ValueError) as exc:
            raise EmbeddingProviderError("OpenAI embeddings response was malformed") from exc

        if len(vectors) != len(texts):
            raise EmbeddingProviderError("OpenAI embeddings response length mismatch")
        return vectors
