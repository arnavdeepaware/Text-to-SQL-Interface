from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import Mock

import pytest
from _pytest.monkeypatch import MonkeyPatch

from app.core.config import Settings
from app.domain.confidence import ValidationSignal
from app.domain.glossary import BusinessGlossary
from app.domain.query_execution import QueryExecutionResult, QueryPlanSummary
from app.domain.schema import ColumnSchema, DatabaseSchema, PrimaryKeySchema, TableSchema
from app.domain.schema_catalog import SchemaCatalog
from app.domain.sql_generation import (
    SQLGenerationDraft,
    SQLGenerationResult,
    SQLGenerationTelemetry,
)
from app.providers.fake_sql_generation import FakeSQLGenerator
from app.providers.sql_generation import SQLGenerationProviderTimeoutError
from app.services.query_draft import (
    ClarificationOption,
    ClarificationRequired,
    QueryDraftResult,
)
from app.services.query_execution import QueryExecutionError, QueryPlanThresholdExceededError
from app.services.query_workflow import (
    QueryWorkflowMissingResultError,
    QueryWorkflowService,
    QueryWorkflowValidationError,
)
from app.services.sql_guardrails import GeneratedSQLValidator, SQLGuardrailValidationError


def test_workflow_executes_normal_question() -> None:
    draft = fake_draft("SELECT order_id FROM commerce.orders")
    executor = FakeExecutor(fake_execution())
    workflow = workflow_service(
        draft_service=FakeDraftService(QueryDraftResult(draft=draft)),
        executor=executor,
    )

    result = workflow.run("  Show all orders  ")

    assert result.question == "Show all orders"
    assert result.draft == draft
    assert result.execution == executor.result
    assert result.confidence is not None
    assert result.confidence.score is not None
    assert executor.calls == 1


def test_workflow_returns_clarification_before_execution() -> None:
    executor = FakeExecutor(fake_execution())
    clarification = ClarificationRequired(
        message="Ambiguous.",
        options=(ClarificationOption("All orders", "Count all orders"),),
    )
    workflow = workflow_service(
        draft_service=FakeDraftService(QueryDraftResult(clarification=clarification)),
        executor=executor,
    )

    result = workflow.run("Show revenue by month")

    assert result.clarification == clarification
    assert executor.calls == 0


def test_workflow_surfaces_generation_failure_without_execution() -> None:
    executor = FakeExecutor(fake_execution())
    workflow = workflow_service(
        draft_service=FailingDraftService(SQLGenerationProviderTimeoutError("timeout")),
        executor=executor,
    )

    with pytest.raises(SQLGenerationProviderTimeoutError):
        workflow.run("Show all orders")

    assert executor.calls == 0


def test_workflow_surfaces_validation_failure_without_execution() -> None:
    validation = GeneratedSQLValidator(Settings(environment="test")).validate(
        "DELETE FROM commerce.orders",
        fake_catalog(),
    )
    executor = FakeExecutor(fake_execution())
    workflow = workflow_service(
        draft_service=FailingDraftService(SQLGuardrailValidationError(validation)),
        executor=executor,
    )

    with pytest.raises(SQLGuardrailValidationError):
        workflow.run("Delete orders")

    assert executor.calls == 0


def test_workflow_surfaces_plan_failure() -> None:
    workflow = workflow_service(
        draft_service=FakeDraftService(QueryDraftResult(draft=fake_draft())),
        executor=FailingExecutor(QueryPlanThresholdExceededError("too expensive")),
    )

    with pytest.raises(QueryPlanThresholdExceededError):
        workflow.run("Show all orders")


def test_workflow_surfaces_execution_failure() -> None:
    workflow = workflow_service(
        draft_service=FakeDraftService(QueryDraftResult(draft=fake_draft())),
        executor=FailingExecutor(QueryExecutionError("execution failed")),
    )

    with pytest.raises(QueryExecutionError):
        workflow.run("Show all orders")


def test_workflow_rejects_invalid_question_before_schema_lookup() -> None:
    catalog_provider = FakeCatalogProvider()
    workflow = workflow_service(catalog_provider=catalog_provider)

    with pytest.raises(QueryWorkflowValidationError) as exc_info:
        workflow.run("   ")

    assert exc_info.value.public_code == "empty_question"
    assert catalog_provider.calls == 0


def test_workflow_logs_invalid_request_audit(monkeypatch: MonkeyPatch) -> None:
    logger = Mock()
    monkeypatch.setattr("app.services.query_workflow.logger", logger)
    workflow = workflow_service(request_id="req-invalid")

    with pytest.raises(QueryWorkflowValidationError):
        workflow.run("   ")

    assert logger.info.call_args_list[0].kwargs["extra"] == {
        "request_id": "req-invalid",
        "event": "started",
    }
    assert logger.info.call_args_list[-1].kwargs["extra"] == {
        "request_id": "req-invalid",
        "event": "invalid_request",
        "error_code": "empty_question",
    }


def test_workflow_missing_draft_result_is_stable_error() -> None:
    workflow = workflow_service(draft_service=FakeDraftService(QueryDraftResult()))

    with pytest.raises(QueryWorkflowMissingResultError):
        workflow.run("Show all orders")


def test_workflow_logs_request_correlated_audit(monkeypatch: MonkeyPatch) -> None:
    logger = Mock()
    monkeypatch.setattr("app.services.query_workflow.logger", logger)
    workflow = workflow_service(
        request_id="req-audit",
        draft_service=FakeDraftService(QueryDraftResult(draft=fake_draft())),
    )

    workflow.run("Show all orders")

    assert logger.info.call_args_list[0].args == ("Query workflow audit",)
    assert logger.info.call_args_list[0].kwargs["extra"]["request_id"] == "req-audit"
    assert logger.info.call_args_list[-1].kwargs["extra"]["event"] == "executed"


def test_workflow_appends_semantic_and_multi_query_signals() -> None:
    semantic_signal = ValidationSignal(
        "semantic_alignment_uncertain",
        "warning",
        0.5,
        "Semantic alignment was uncertain.",
    )
    multi_signal = ValidationSignal(
        "multi_query_result_agreement",
        "passed",
        1.0,
        "Independent SQL agreed.",
    )
    semantic_validator = StaticSemanticValidator((semantic_signal,))
    multi_validator = StaticMultiValidator((multi_signal,))
    workflow = workflow_service(
        draft_service=FakeDraftService(QueryDraftResult(draft=fake_draft())),
        semantic_validator=semantic_validator,
        multi_query_validator=multi_validator,
    )

    result = workflow.run("Show all orders")

    assert semantic_validator.calls == 1
    assert multi_validator.calls == 1
    assert semantic_signal in result.validation_signals
    assert multi_signal in result.validation_signals
    assert result.confidence is not None
    assert result.confidence.score is not None
    assert "semantic_alignment_uncertain" in multi_validator.signal_codes_seen


def workflow_service(
    draft_service: FakeDraftService | FailingDraftService | None = None,
    executor: FakeExecutor | FailingExecutor | None = None,
    catalog_provider: FakeCatalogProvider | None = None,
    request_id: str = "req-test",
    semantic_validator: StaticSemanticValidator | None = None,
    multi_query_validator: StaticMultiValidator | None = None,
) -> QueryWorkflowService:
    return QueryWorkflowService(
        settings=Settings(environment="test"),
        catalog_provider=catalog_provider or FakeCatalogProvider(),
        sql_generator=FakeSQLGenerator(),
        query_executor=executor or FakeExecutor(fake_execution()),
        request_id=request_id,
        draft_service=draft_service
        or FakeDraftService(QueryDraftResult(draft=fake_draft())),
        semantic_validator=semantic_validator,
        multi_query_validator=multi_query_validator,
    )


@dataclass
class FakeCatalogProvider:
    calls: int = 0

    def get_schema(self, refresh: bool = False) -> SchemaCatalog:
        self.calls += 1
        return fake_catalog()


@dataclass
class FakeDraftService:
    result: QueryDraftResult

    def draft(self, question: str, catalog: SchemaCatalog) -> QueryDraftResult:
        return self.result


@dataclass
class FailingDraftService:
    error: Exception

    def draft(self, question: str, catalog: SchemaCatalog) -> QueryDraftResult:
        raise self.error


@dataclass
class FakeExecutor:
    result: QueryExecutionResult
    calls: int = 0

    def execute(self, sql: str, catalog: SchemaCatalog) -> QueryExecutionResult:
        self.calls += 1
        return self.result


@dataclass
class FailingExecutor:
    error: Exception

    def execute(self, sql: str, catalog: SchemaCatalog) -> QueryExecutionResult:
        raise self.error


@dataclass
class StaticSemanticValidator:
    signals: tuple[ValidationSignal, ...]
    calls: int = 0

    def validate(self, request: Any) -> tuple[ValidationSignal, ...]:
        self.calls += 1
        return self.signals


@dataclass
class StaticMultiValidator:
    signals: tuple[ValidationSignal, ...]
    calls: int = 0
    signal_codes_seen: tuple[str, ...] = ()

    def evaluate(self, request: Any) -> tuple[ValidationSignal, ...]:
        self.calls += 1
        self.signal_codes_seen = tuple(signal.code for signal in request.validation_signals)
        return self.signals


def fake_draft(sql: str = "SELECT order_id FROM commerce.orders") -> SQLGenerationDraft:
    return SQLGenerationDraft(
        result=SQLGenerationResult(
            sql=sql,
            explanation="Explains the query.",
            model_confidence=0.8,
            tables_used=["commerce.orders"],
            columns_used=["commerce.orders.order_id"],
            assumptions=[],
            clarification_needed=False,
            clarification_options=[],
        ),
        telemetry=SQLGenerationTelemetry(
            provider_name="fake",
            model_name="fake-sql-generator",
            provider_latency_ms=1,
        ),
    )


def fake_execution() -> QueryExecutionResult:
    return QueryExecutionResult(
        executed_sql="SELECT order_id FROM commerce.orders LIMIT 1000",
        columns=(),
        rows=(),
        row_count=0,
        execution_duration_ms=1,
        truncated=False,
        plan=QueryPlanSummary(
            estimated_rows=1,
            total_cost=1.0,
            plan_nodes=("Result",),
            referenced_relations=(),
        ),
    )


def fake_catalog() -> SchemaCatalog:
    return SchemaCatalog(
        database_schema=DatabaseSchema(
            schemas=("commerce",),
            tables=(
                TableSchema(
                    schema_name="commerce",
                    name="orders",
                    columns=(ColumnSchema("order_id", "BIGINT", False),),
                    primary_key=PrimaryKeySchema(("order_id",), "orders_pkey"),
                ),
            ),
        ),
        samples=(),
        glossary=BusinessGlossary(version=1, terms=()),
        generated_at_epoch_seconds=0,
        cache_expires_at_epoch_seconds=0,
        refreshed=False,
    )
