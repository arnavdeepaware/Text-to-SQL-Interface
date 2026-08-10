from __future__ import annotations

from app.core.config import Settings
from app.domain.query_execution import QueryExecutionResult, QueryPlanSummary, QueryResultColumn
from app.domain.sql_guardrails import ReferencedColumn, ReferencedTable, SQLValidationMetadata
from app.providers.alignment import BackTranslationResult
from app.providers.embeddings import EmbeddingProviderError
from app.providers.fake_alignment import FakeBackTranslationProvider
from app.services.semantic_alignment import (
    EmbeddingLexicalQuestionAligner,
    SemanticAlignmentRequest,
    SemanticAlignmentService,
)


def test_semantic_alignment_passes_with_embedding_similarity() -> None:
    settings = Settings(environment="test", confidence_semantic_enabled=True)
    service = SemanticAlignmentService(
        settings,
        back_translation_provider=FakeBackTranslationProvider(
            result=BackTranslationResult(
                question="Show gross revenue by month",
                summary="Computes monthly gross revenue from orders.",
                semantic_claims=["metric=gross revenue", "grain=month"],
                referenced_tables=["commerce.orders"],
                referenced_columns=["commerce.orders.total_cents"],
            )
        ),
        question_aligner=EmbeddingLexicalQuestionAligner(settings, MatchingEmbeddingProvider()),
    )

    signals = service.validate(
        SemanticAlignmentRequest(
            question="Show gross revenue by month",
            execution=execution(),
        )
    )

    assert signals[0].code == "semantic_alignment_passed"
    assert signals[0].status == "passed"
    assert signals[0].evidence["method"] == "embedding"
    assert signals[0].evidence["back_translated_question"] == "Show gross revenue by month"


def test_semantic_alignment_provider_timeout_becomes_unavailable_signal() -> None:
    service = SemanticAlignmentService(
        Settings(environment="test", confidence_semantic_enabled=True),
        back_translation_provider=FakeBackTranslationProvider(mode="timeout"),
    )

    signals = service.validate(
        SemanticAlignmentRequest(
            question="Show gross revenue by month",
            execution=execution(),
        )
    )

    assert signals[0].code == "back_translation_provider_timeout"
    assert signals[0].status == "unavailable"
    assert signals[0].evidence["stage"] == "back_translation"


def test_embedding_failure_uses_capped_lexical_fallback_without_passing() -> None:
    settings = Settings(environment="test", confidence_semantic_enabled=True)
    service = SemanticAlignmentService(
        settings,
        back_translation_provider=FakeBackTranslationProvider(
            result=BackTranslationResult(
                question="Show gross revenue by month",
                summary="Computes monthly gross revenue from orders.",
            )
        ),
        question_aligner=EmbeddingLexicalQuestionAligner(settings, FailingEmbeddingProvider()),
    )

    signals = service.validate(
        SemanticAlignmentRequest(
            question="Show gross revenue by month",
            execution=execution(),
        )
    )

    assert signals[0].code == "semantic_alignment_uncertain"
    assert signals[0].status == "warning"
    assert signals[0].score == settings.confidence_alignment_lexical_score_cap
    assert signals[0].evidence["method"] == "lexical_fallback"
    assert signals[0].evidence["fallback_reason"] == "embedding_provider_unavailable"


def test_lexical_alignment_detects_clear_semantic_mismatch() -> None:
    service = SemanticAlignmentService(
        Settings(environment="test", confidence_semantic_enabled=True),
        back_translation_provider=FakeBackTranslationProvider(
            result=BackTranslationResult(
                question="Which customer records are returned?",
                summary="Returns customers.",
            )
        ),
    )

    signals = service.validate(
        SemanticAlignmentRequest(
            question="Show gross revenue by month",
            execution=execution(),
        )
    )

    assert signals[0].code == "semantic_alignment_mismatch"
    assert signals[0].status == "failed"
    assert signals[0].evidence["method"] == "lexical"


def test_semantic_alignment_disabled_returns_no_signal() -> None:
    service = SemanticAlignmentService(Settings(environment="test"))

    assert service.validate(
        SemanticAlignmentRequest(
            question="Show gross revenue by month",
            execution=execution(),
        )
    ) == ()


class MatchingEmbeddingProvider:
    @property
    def is_configured(self) -> bool:
        return True

    def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        assert len(texts) == 2
        return ((1.0, 0.0), (1.0, 0.0))


class FailingEmbeddingProvider:
    @property
    def is_configured(self) -> bool:
        return True

    def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        raise EmbeddingProviderError("fake embedding outage")


def execution() -> QueryExecutionResult:
    return QueryExecutionResult(
        executed_sql=(
            "SELECT date_trunc('month', orders.ordered_at) AS month, "
            "sum(orders.total_cents) AS gross_revenue "
            "FROM commerce.orders AS orders GROUP BY 1 LIMIT 1000"
        ),
        columns=(QueryResultColumn("month"), QueryResultColumn("gross_revenue")),
        rows=({"month": "2026-01-01", "gross_revenue": 1000},),
        row_count=1,
        execution_duration_ms=2,
        truncated=False,
        plan=QueryPlanSummary(
            estimated_rows=1,
            total_cost=1.0,
            plan_nodes=("Aggregate",),
            referenced_relations=("commerce.orders",),
        ),
        guardrail_metadata=SQLValidationMetadata(
            statement_type="select",
            referenced_tables=(
                ReferencedTable(schema_name="commerce", name="orders", alias="orders"),
            ),
            referenced_columns=(
                ReferencedColumn(
                    name="ordered_at",
                    source_name="orders",
                    table_identifier="commerce.orders",
                ),
                ReferencedColumn(
                    name="total_cents",
                    source_name="orders",
                    table_identifier="commerce.orders",
                ),
            ),
            functions=("sum",),
        ),
    )
