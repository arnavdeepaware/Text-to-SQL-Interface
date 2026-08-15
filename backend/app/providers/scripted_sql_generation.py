from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.prompt import SQLGenerationPrompt
from app.domain.sql_generation import (
    SQLGenerationDraft,
    SQLGenerationResult,
    SQLGenerationTelemetry,
)
from app.providers.sql_generation import SQLGenerationProviderUnavailableError


@dataclass(frozen=True)
class ScriptedSQLGenerator:
    """Deterministic evaluation provider keyed only by the prompt question."""

    responses: dict[str, SQLGenerationResult]

    def generate(self, prompt: SQLGenerationPrompt) -> SQLGenerationDraft:
        question = normalize_question(prompt.original_question)
        result = self.responses.get(question)
        if result is None:
            raise SQLGenerationProviderUnavailableError("No scripted evaluation response exists")
        return SQLGenerationDraft(
            result=result,
            telemetry=SQLGenerationTelemetry(
                provider_name="scripted_fake",
                model_name="scripted-evaluation-generator",
                provider_latency_ms=0,
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                retry_count=0,
            ),
        )


def normalize_question(question: str) -> str:
    return re.sub(r"\s+", " ", question).strip().casefold()
