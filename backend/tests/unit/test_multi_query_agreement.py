from __future__ import annotations

from dataclasses import dataclass

from _pytest.monkeypatch import MonkeyPatch

from app.core.config import Settings
from app.domain.confidence import ValidationSignal
from app.domain.glossary import BusinessGlossary
from app.domain.prompt import SQLGenerationPrompt
from app.domain.query_execution import QueryExecutionResult, QueryPlanSummary, QueryResultColumn
from app.domain.schema import ColumnSchema, DatabaseSchema, PrimaryKeySchema, TableSchema
from app.domain.schema_catalog import SchemaCatalog
from app.domain.schema_retrieval import RankedColumn, RankedTable, SchemaRetrievalResult
from app.domain.sql_generation import (
    SQLGenerationDraft,
    SQLGenerationResult,
    SQLGenerationTelemetry,
)
from app.domain.sql_guardrails import SQLValidationResult
from app.providers.sql_generation import SQLGenerationProviderTimeoutError
from app.services.multi_query_agreement import (
    MultiQueryAgreementRequest,
    MultiQueryAgreementService,
)
from app.services.sql_guardrails import GeneratedSQLValidator, SQLGuardrailValidationError


def test_multi_query_skips_simple_lookup_without_provider_or_execution_calls() -> None:
    settings = Settings(environment="test", confidence_multi_query_enabled=True)
    catalog = fake_catalog()
    primary = guarded_execution(
        "SELECT order_id FROM commerce.orders",
        rows=({"order_id": 1},),
        columns=(QueryResultColumn("order_id"),),
        settings=settings,
        catalog=catalog,
    )
    generator = RecordingGenerator(sql="SELECT order_id FROM commerce.orders")
    executor = GuardedFakeExecutor(settings, rows=({"order_id": 1},))
    service = MultiQueryAgreementService(settings, generator, executor)

    signals = service.evaluate(
        request(
            question="Show order 1",
            catalog=catalog,
            primary_execution=primary,
        )
    )

    assert signals[0].code == "multi_query_not_applicable_simple_lookup"
    assert signals[0].status == "not_applicable"
    assert generator.calls == 0
    assert executor.sql_calls == ()


def test_multi_query_reports_agreement_for_matching_results_with_different_sql_forms() -> None:
    settings = Settings(environment="test", confidence_multi_query_enabled=True)
    catalog = fake_catalog()
    primary = guarded_execution(
        "SELECT count(*) AS order_count FROM commerce.orders",
        rows=({"order_count": 3},),
        columns=(QueryResultColumn("order_count"),),
        settings=settings,
        catalog=catalog,
    )
    generator = RecordingGenerator(
        sql="SELECT count(orders.order_id) AS order_count FROM commerce.orders AS orders"
    )
    executor = GuardedFakeExecutor(settings, rows=({"order_count": 3},))
    service = MultiQueryAgreementService(settings, generator, executor)

    signals = service.evaluate(
        request(
            question="Count all orders",
            catalog=catalog,
            primary_execution=primary,
        )
    )

    assert signals[0].code == "multi_query_result_agreement"
    assert signals[0].status == "passed"
    assert executor.sql_calls == (
        "SELECT count(orders.order_id) AS order_count FROM commerce.orders AS orders",
    )
    assert generator.prompts
    assert primary.executed_sql not in generator.prompts[0].text
    assert "primary result" in generator.prompts[0].text.casefold()


def test_multi_query_reports_true_result_disagreement() -> None:
    settings = Settings(environment="test", confidence_multi_query_enabled=True)
    catalog = fake_catalog()
    primary = guarded_execution(
        "SELECT count(*) AS order_count FROM commerce.orders",
        rows=({"order_count": 3},),
        columns=(QueryResultColumn("order_count"),),
        settings=settings,
        catalog=catalog,
    )
    generator = RecordingGenerator(
        sql="SELECT count(orders.order_id) AS order_count FROM commerce.orders AS orders"
    )
    executor = GuardedFakeExecutor(settings, rows=({"order_count": 4},))
    service = MultiQueryAgreementService(settings, generator, executor)

    signals = service.evaluate(
        request(
            question="Count all orders",
            catalog=catalog,
            primary_execution=primary,
        )
    )

    assert signals[0].code == "multi_query_result_disagreement"
    assert signals[0].status == "failed"
    assert signals[0].evidence["comparison_code"] == "result_comparison_value_mismatch"


def test_multi_query_ignores_secondary_model_confidence_for_agreement() -> None:
    settings = Settings(environment="test", confidence_multi_query_enabled=True)
    catalog = fake_catalog()
    primary = guarded_execution(
        "SELECT count(*) AS order_count FROM commerce.orders",
        rows=({"order_count": 3},),
        columns=(QueryResultColumn("order_count"),),
        settings=settings,
        catalog=catalog,
    )
    generator = RecordingGenerator(
        sql="SELECT count(orders.order_id) AS order_count FROM commerce.orders AS orders",
        model_confidence=1.0,
    )
    executor = GuardedFakeExecutor(settings, rows=({"order_count": 99},))
    service = MultiQueryAgreementService(settings, generator, executor)

    signals = service.evaluate(
        request(
            question="Count all orders",
            catalog=catalog,
            primary_execution=primary,
        )
    )

    assert signals[0].code == "multi_query_result_disagreement"
    assert signals[0].status == "failed"
    assert "model_confidence" not in signals[0].evidence


def test_multi_query_reports_inability_to_compare() -> None:
    settings = Settings(environment="test", confidence_multi_query_enabled=True)
    catalog = fake_catalog()
    primary = guarded_execution(
        "SELECT count(*) AS order_count FROM commerce.orders",
        rows=({"order_count": 3},),
        columns=(QueryResultColumn("order_count"),),
        settings=settings,
        catalog=catalog,
    )
    generator = RecordingGenerator(
        sql="SELECT count(orders.order_id) AS total_orders FROM commerce.orders AS orders"
    )
    executor = GuardedFakeExecutor(
        settings,
        rows=({"total_orders": 3},),
        columns=(QueryResultColumn("total_orders"),),
    )
    service = MultiQueryAgreementService(settings, generator, executor)

    signals = service.evaluate(
        request(
            question="Count all orders",
            catalog=catalog,
            primary_execution=primary,
        )
    )

    assert signals[0].code == "multi_query_result_incomparable"
    assert signals[0].status == "warning"
    assert signals[0].evidence["comparison_code"] == "result_comparison_column_mismatch"


def test_multi_query_provider_failure_becomes_unavailable_signal() -> None:
    settings = Settings(environment="test", confidence_multi_query_enabled=True)
    catalog = fake_catalog()
    primary = guarded_execution(
        "SELECT count(*) AS order_count FROM commerce.orders",
        rows=({"order_count": 3},),
        columns=(QueryResultColumn("order_count"),),
        settings=settings,
        catalog=catalog,
    )
    service = MultiQueryAgreementService(
        settings,
        RecordingGenerator(error=SQLGenerationProviderTimeoutError("timeout")),
        GuardedFakeExecutor(settings, rows=({"order_count": 3},)),
    )

    signals = service.evaluate(
        request(
            question="Count all orders",
            catalog=catalog,
            primary_execution=primary,
        )
    )

    assert signals[0].code == "multi_query_generation_unavailable"
    assert signals[0].status == "unavailable"
    assert signals[0].evidence["generation_error_code"] == "sql_generation_provider_timeout"


def test_multi_query_timeout_becomes_unavailable_signal(monkeypatch: MonkeyPatch) -> None:
    ticks = iter((0.0, 0.2, 0.2))
    monkeypatch.setattr(
        "app.services.multi_query_agreement.perf_counter",
        lambda: next(ticks),
    )
    settings = Settings(
        environment="test",
        confidence_multi_query_enabled=True,
        confidence_multi_query_timeout_seconds=0.1,
    )
    catalog = fake_catalog()
    primary = guarded_execution(
        "SELECT count(*) AS order_count FROM commerce.orders",
        rows=({"order_count": 3},),
        columns=(QueryResultColumn("order_count"),),
        settings=settings,
        catalog=catalog,
    )
    service = MultiQueryAgreementService(
        settings,
        RecordingGenerator(
            sql="SELECT count(orders.order_id) AS order_count FROM commerce.orders AS orders"
        ),
        GuardedFakeExecutor(settings, rows=({"order_count": 3},)),
    )

    signals = service.evaluate(
        request(
            question="Count all orders",
            catalog=catalog,
            primary_execution=primary,
        )
    )

    assert signals[0].code == "multi_query_timeout"
    assert signals[0].status == "unavailable"


def test_unsafe_secondary_sql_is_blocked_by_guarded_executor() -> None:
    settings = Settings(environment="test", confidence_multi_query_enabled=True)
    catalog = fake_catalog()
    primary = guarded_execution(
        "SELECT count(*) AS order_count FROM commerce.orders",
        rows=({"order_count": 3},),
        columns=(QueryResultColumn("order_count"),),
        settings=settings,
        catalog=catalog,
    )
    executor = GuardedFakeExecutor(settings, rows=({"order_count": 3},))
    service = MultiQueryAgreementService(
        settings,
        RecordingGenerator(sql="DELETE FROM commerce.orders"),
        executor,
    )

    signals = service.evaluate(
        request(
            question="Count all orders",
            catalog=catalog,
            primary_execution=primary,
        )
    )

    assert signals[0].code == "multi_query_secondary_blocked"
    assert signals[0].status == "unavailable"
    assert executor.sql_calls == ("DELETE FROM commerce.orders",)


def request(
    question: str,
    catalog: SchemaCatalog,
    primary_execution: QueryExecutionResult,
    validation_signals: tuple[ValidationSignal, ...] = (),
) -> MultiQueryAgreementRequest:
    return MultiQueryAgreementRequest(
        question=question,
        catalog=catalog,
        retrieval=retrieval(question),
        primary_draft=draft(primary_execution.executed_sql),
        primary_execution=primary_execution,
        validation_signals=validation_signals,
    )


@dataclass
class RecordingGenerator:
    sql: str = "SELECT 1"
    error: Exception | None = None
    model_confidence: float = 0.2
    retry_count: int = 0
    calls: int = 0
    prompts: tuple[SQLGenerationPrompt, ...] = ()

    def generate(self, prompt: SQLGenerationPrompt) -> SQLGenerationDraft:
        self.calls += 1
        self.prompts = (*self.prompts, prompt)
        if self.error is not None:
            raise self.error
        return draft(
            self.sql,
            retry_count=self.retry_count,
            model_confidence=self.model_confidence,
        )


@dataclass
class GuardedFakeExecutor:
    settings: Settings
    rows: tuple[dict[str, object], ...]
    columns: tuple[QueryResultColumn, ...] = (QueryResultColumn("order_count"),)
    sql_calls: tuple[str, ...] = ()

    def execute(self, sql: str, catalog: SchemaCatalog) -> QueryExecutionResult:
        self.sql_calls = (*self.sql_calls, sql)
        return guarded_execution(
            sql,
            rows=self.rows,
            columns=self.columns,
            settings=self.settings,
            catalog=catalog,
        )


def guarded_execution(
    sql: str,
    rows: tuple[dict[str, object], ...],
    columns: tuple[QueryResultColumn, ...],
    settings: Settings,
    catalog: SchemaCatalog,
) -> QueryExecutionResult:
    validation = GeneratedSQLValidator(settings).validate(sql, catalog)
    if not validation.valid:
        raise SQLGuardrailValidationError(validation)
    return execution_from_validation(validation, rows, columns)


def execution_from_validation(
    validation: SQLValidationResult,
    rows: tuple[dict[str, object], ...],
    columns: tuple[QueryResultColumn, ...],
) -> QueryExecutionResult:
    return QueryExecutionResult(
        executed_sql=validation.sql,
        columns=columns,
        rows=rows,
        row_count=len(rows),
        execution_duration_ms=2,
        truncated=False,
        plan=QueryPlanSummary(
            estimated_rows=len(rows),
            total_cost=1.0,
            plan_nodes=("Aggregate",),
            referenced_relations=("commerce.orders",),
        ),
        guardrail_metadata=validation.metadata,
        guardrail_findings=validation.findings,
    )


def draft(
    sql: str,
    retry_count: int = 0,
    model_confidence: float = 0.2,
) -> SQLGenerationDraft:
    return SQLGenerationDraft(
        result=SQLGenerationResult(
            sql=sql,
            explanation="Generated alternate SQL.",
            model_confidence=model_confidence,
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
            retry_count=retry_count,
        ),
    )


def retrieval(question: str) -> SchemaRetrievalResult:
    return SchemaRetrievalResult(
        question=question,
        strategy="lexical",
        ranked_tables=(
            RankedTable(
                identifier="commerce.orders",
                schema_name="commerce",
                table_name="orders",
                score=10.0,
                reasons=(),
                selected=True,
            ),
        ),
        ranked_columns=(
            RankedColumn(
                table_identifier="commerce.orders",
                column_name="order_id",
                score=8.0,
                reasons=(),
                selected=True,
            ),
        ),
        relationship_paths=(),
        glossary_terms=(),
    )


def fake_catalog() -> SchemaCatalog:
    return SchemaCatalog(
        database_schema=DatabaseSchema(
            schemas=("commerce",),
            tables=(
                TableSchema(
                    schema_name="commerce",
                    name="orders",
                    columns=(
                        ColumnSchema("order_id", "BIGINT", False),
                        ColumnSchema("total_cents", "BIGINT", False),
                        ColumnSchema("ordered_at", "TIMESTAMP", False),
                    ),
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
