from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from app.core.config import Settings
from app.domain.confidence import ValidationSignal
from app.domain.query_execution import QueryExecutionResult
from app.providers.alignment import (
    BackTranslationDraft,
    BackTranslationInput,
    BackTranslationProviderError,
    SQLBackTranslator,
)
from app.providers.embeddings import (
    EmbeddingProvider,
    EmbeddingProviderError,
    OpenAIEmbeddingProvider,
)
from app.providers.fake_alignment import FakeBackTranslationProvider
from app.providers.openai_alignment import OpenAIBackTranslationProvider

AlignmentMethod = Literal["embedding", "lexical", "lexical_fallback"]


@dataclass(frozen=True)
class SemanticAlignmentRequest:
    """Inputs available after guarded execution for probabilistic semantic validation."""

    question: str
    execution: QueryExecutionResult


@dataclass(frozen=True)
class QuestionAlignmentResult:
    """Explainable original-question versus back-translation comparison."""

    method: AlignmentMethod
    score: float
    lexical_score: float
    embedding_score: float | None
    overlapping_terms: tuple[str, ...]
    missing_original_terms: tuple[str, ...]
    extra_back_translation_terms: tuple[str, ...]
    fallback_reason: str | None = None


class QuestionAligner(Protocol):
    """Provider-neutral question alignment scorer."""

    def align(
        self,
        original_question: str,
        back_translated_question: str,
    ) -> QuestionAlignmentResult:
        ...


class SemanticAlignmentService:
    """Back-translate executed SQL and emit an explainable semantic alignment signal."""

    def __init__(
        self,
        settings: Settings,
        back_translation_provider: SQLBackTranslator | None = None,
        question_aligner: QuestionAligner | None = None,
    ) -> None:
        self._settings = settings
        self._back_translation_provider = back_translation_provider
        self._question_aligner = question_aligner or EmbeddingLexicalQuestionAligner(settings)

    def validate(self, request: SemanticAlignmentRequest) -> tuple[ValidationSignal, ...]:
        if not self._settings.confidence_semantic_enabled:
            return ()

        metadata = request.execution.guardrail_metadata
        if metadata is None:
            return (
                unavailable_signal(
                    "semantic_alignment_metadata_unavailable",
                    "Semantic alignment could not run because AST metadata is unavailable.",
                ),
            )
        if not request.execution.executed_sql:
            return (
                unavailable_signal(
                    "semantic_alignment_sql_unavailable",
                    "Semantic alignment could not run because executed SQL is unavailable.",
                ),
            )

        provider = self._back_translation_provider or default_back_translation_provider(
            self._settings
        )
        try:
            back_translation = provider.back_translate(
                BackTranslationInput(
                    executed_sql=request.execution.executed_sql,
                    columns=request.execution.columns,
                    referenced_tables=tuple(
                        table.identifier
                        for table in metadata.referenced_tables
                        if table.source == "table"
                    ),
                    referenced_columns=tuple(
                        column.identifier
                        for column in metadata.referenced_columns
                        if column.table_identifier is not None
                    ),
                    functions=metadata.functions,
                    row_count=request.execution.row_count,
                    truncated=request.execution.truncated,
                )
            )
        except BackTranslationProviderError as exc:
            return (
                unavailable_signal(
                    exc.public_code,
                    exc.public_message,
                    {
                        "stage": "back_translation",
                        "provider": provider_name(provider),
                        "sql_hash": sql_hash(request.execution.executed_sql),
                    },
                ),
            )

        alignment = self._question_aligner.align(
            request.question,
            back_translation.result.question,
        )
        return (alignment_signal(request, back_translation, alignment, self._settings),)


class EmbeddingLexicalQuestionAligner:
    """Score question similarity with embeddings when configured, else lexical overlap."""

    def __init__(
        self,
        settings: Settings,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self._settings = settings
        self._embedding_provider = embedding_provider or OpenAIEmbeddingProvider(settings)

    def align(
        self,
        original_question: str,
        back_translated_question: str,
    ) -> QuestionAlignmentResult:
        original_terms = tokenize(original_question)
        translated_terms = tokenize(back_translated_question)
        lexical_score = lexical_similarity(original_terms, translated_terms)
        overlapping_terms = tuple(sorted(original_terms & translated_terms))
        missing_terms = tuple(sorted(original_terms - translated_terms))
        extra_terms = tuple(sorted(translated_terms - original_terms))

        if self._embedding_provider.is_configured:
            try:
                vectors = self._embedding_provider.embed(
                    (original_question, back_translated_question)
                )
            except EmbeddingProviderError:
                return lexical_result(
                    lexical_score,
                    overlapping_terms,
                    missing_terms,
                    extra_terms,
                    self._settings,
                    fallback_reason="embedding_provider_unavailable",
                    method="lexical_fallback",
                )
            if len(vectors) == 2:
                embedding_score = cosine_similarity(vectors[0], vectors[1])
                combined_score = clamp(0.7 * embedding_score + 0.3 * lexical_score)
                return QuestionAlignmentResult(
                    method="embedding",
                    score=combined_score,
                    lexical_score=lexical_score,
                    embedding_score=embedding_score,
                    overlapping_terms=overlapping_terms,
                    missing_original_terms=missing_terms,
                    extra_back_translation_terms=extra_terms,
                )

        return lexical_result(
            lexical_score,
            overlapping_terms,
            missing_terms,
            extra_terms,
            self._settings,
            fallback_reason=None,
            method="lexical",
        )


def default_back_translation_provider(settings: Settings) -> SQLBackTranslator:
    if settings.confidence_alignment_provider == "fake":
        return FakeBackTranslationProvider()
    return OpenAIBackTranslationProvider(settings)


def alignment_signal(
    request: SemanticAlignmentRequest,
    back_translation: BackTranslationDraft,
    alignment: QuestionAlignmentResult,
    settings: Settings,
) -> ValidationSignal:
    status = alignment_status(alignment, settings)
    evidence: dict[str, Any] = {
        "method": alignment.method,
        "back_translated_question": back_translation.result.question,
        "summary": back_translation.result.summary,
        "semantic_claims": back_translation.result.semantic_claims,
        "similarity_score": alignment.score,
        "lexical_score": alignment.lexical_score,
        "embedding_score": alignment.embedding_score,
        "overlapping_terms": alignment.overlapping_terms,
        "missing_original_terms": alignment.missing_original_terms[:12],
        "extra_back_translation_terms": alignment.extra_back_translation_terms[:12],
        "fallback_reason": alignment.fallback_reason,
        "thresholds": {
            "pass": settings.confidence_alignment_pass_threshold,
            "fail": settings.confidence_alignment_fail_threshold,
            "lexical_score_cap": settings.confidence_alignment_lexical_score_cap,
        },
        "provider": back_translation.telemetry.provider_name,
        "model": back_translation.telemetry.model_name,
        "provider_latency_ms": back_translation.telemetry.provider_latency_ms,
        "retry_count": back_translation.telemetry.retry_count,
        "sql_hash": sql_hash(request.execution.executed_sql),
    }
    if status == "passed":
        return ValidationSignal(
            "semantic_alignment_passed",
            "passed",
            alignment.score,
            "Back-translated SQL question aligns with the original question.",
            evidence,
        )
    if status == "failed":
        return ValidationSignal(
            "semantic_alignment_mismatch",
            "failed",
            alignment.score,
            "Back-translated SQL question appears materially different from the original question.",
            evidence,
        )
    return ValidationSignal(
        "semantic_alignment_uncertain",
        "warning",
        alignment.score,
        "Back-translated SQL question only partially aligns with the original question.",
        evidence,
    )


def alignment_status(
    alignment: QuestionAlignmentResult,
    settings: Settings,
) -> Literal["passed", "warning", "failed"]:
    if alignment.score <= settings.confidence_alignment_fail_threshold:
        return "failed"
    if (
        alignment.method == "embedding"
        and alignment.score >= settings.confidence_alignment_pass_threshold
    ):
        return "passed"
    return "warning"


def lexical_result(
    lexical_score: float,
    overlapping_terms: tuple[str, ...],
    missing_terms: tuple[str, ...],
    extra_terms: tuple[str, ...],
    settings: Settings,
    fallback_reason: str | None,
    method: AlignmentMethod,
) -> QuestionAlignmentResult:
    return QuestionAlignmentResult(
        method=method,
        score=min(lexical_score, settings.confidence_alignment_lexical_score_cap),
        lexical_score=lexical_score,
        embedding_score=None,
        overlapping_terms=overlapping_terms,
        missing_original_terms=missing_terms,
        extra_back_translation_terms=extra_terms,
        fallback_reason=fallback_reason,
    )


def lexical_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    precision = len(left & right) / len(right)
    recall = len(left & right) / len(left)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def cosine_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return clamp((dot / (left_norm * right_norm) + 1.0) / 2.0)


def tokenize(text: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", text).casefold().replace("_", " ")
    return {
        token
        for token in re.findall(r"[a-z0-9]+", normalized)
        if token not in STOPWORDS and len(token) > 1
    }


def clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def sql_hash(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()[:16]


def provider_name(provider: SQLBackTranslator) -> str:
    return str(getattr(provider, "provider_name", provider.__class__.__name__))


def unavailable_signal(
    code: str,
    explanation: str,
    evidence: dict[str, Any] | None = None,
) -> ValidationSignal:
    return ValidationSignal(code, "unavailable", 0.0, explanation, evidence or {})


STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "by",
        "does",
        "for",
        "from",
        "how",
        "in",
        "is",
        "of",
        "on",
        "or",
        "per",
        "show",
        "the",
        "to",
        "what",
        "which",
        "with",
    }
)
