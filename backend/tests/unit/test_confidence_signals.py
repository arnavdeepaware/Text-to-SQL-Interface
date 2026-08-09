from __future__ import annotations

from datetime import date

from app.core.config import Settings
from app.domain.confidence import ValidationSignal
from app.domain.glossary import BusinessGlossary, GlossaryTerm
from app.domain.query_execution import QueryExecutionResult, QueryPlanSummary, QueryResultColumn
from app.domain.schema import (
    ColumnSchema,
    DatabaseSchema,
    ForeignKeySchema,
    PrimaryKeySchema,
    TableSchema,
)
from app.domain.schema_catalog import SchemaCatalog
from app.domain.schema_retrieval import RankedColumn, RankedTable, SchemaRetrievalResult
from app.domain.sql_generation import (
    SQLGenerationDraft,
    SQLGenerationResult,
    SQLGenerationTelemetry,
)
from app.domain.sql_guardrails import ReferencedColumn, ReferencedTable, SQLValidationMetadata
from app.services.confidence_signals import (
    DeterministicValidationRequest,
    DeterministicValidationService,
)


def test_schema_coverage_passes_for_retrieved_references() -> None:
    signals = validate(
        retrieval=retrieval(("commerce.orders",), ("commerce.orders.total_cents",)),
        metadata=metadata(
            tables=("commerce.orders",),
            columns=("commerce.orders.total_cents",),
            functions=("sum",),
        ),
        draft=draft(
            tables=("commerce.orders",),
            columns=("commerce.orders.total_cents",),
        ),
    )

    assert signal(signals, "schema_coverage_passed").status == "passed"
    assert signal(signals, "generated_metadata_matches_ast").status == "passed"


def test_schema_coverage_warns_for_unexplained_table_and_column_usage() -> None:
    signals = validate(
        retrieval=retrieval(("commerce.orders",), ("commerce.orders.total_cents",)),
        metadata=metadata(
            tables=("commerce.orders", "commerce.payments"),
            columns=("commerce.orders.total_cents", "commerce.payments.amount_cents"),
            functions=("sum",),
        ),
        draft=draft(
            tables=("commerce.orders", "commerce.payments"),
            columns=("commerce.orders.total_cents", "commerce.payments.amount_cents"),
        ),
    )

    coverage = signal(signals, "schema_coverage_gap")
    assert coverage.status == "warning"
    assert coverage.evidence["unexplained_tables"] == ["commerce.payments"]
    assert coverage.evidence["unexplained_columns"] == ["commerce.payments.amount_cents"]


def test_generated_metadata_mismatch_warns_without_blocking() -> None:
    signals = validate(
        retrieval=retrieval(("commerce.orders",), ("commerce.orders.total_cents",)),
        metadata=metadata(
            tables=("commerce.orders",),
            columns=("commerce.orders.total_cents",),
            functions=("sum",),
        ),
        draft=draft(tables=("commerce.customers",), columns=("commerce.customers.region",)),
    )

    mismatch = signal(signals, "generated_metadata_mismatch")
    assert mismatch.status == "warning"
    assert mismatch.evidence["table_mismatches"] == ["commerce.customers", "commerce.orders"]


def test_result_sanity_detects_failed_numeric_bounds_and_date_warnings() -> None:
    signals = validate(
        rows=(
            {
                "order_count": -1,
                "refund_percent": 125.0,
                "ordered_at": date(2040, 1, 1),
            },
        ),
        columns=(
            QueryResultColumn("order_count"),
            QueryResultColumn("refund_percent"),
            QueryResultColumn("ordered_at"),
        ),
    )

    assert signal(signals, "negative_count_detected").status == "failed"
    assert signal(signals, "percentage_out_of_bounds").status == "failed"
    assert signal(signals, "date_outside_configured_range").status == "warning"


def test_result_sanity_warns_for_null_heavy_and_empty_results() -> None:
    null_signals = validate(
        rows=({"delivered_at": None}, {"delivered_at": None}),
        columns=(QueryResultColumn("delivered_at"),),
    )
    empty_signals = validate(rows=(), columns=(QueryResultColumn("order_id"),))

    assert signal(null_signals, "null_heavy_output_column").status == "warning"
    assert signal(empty_signals, "unexpected_empty_result").status == "warning"


def test_duplicate_amplification_warns_for_count_across_one_to_many_without_distinct() -> None:
    signals = validate(
        question="Count orders by product",
        metadata=metadata(
            tables=("commerce.orders", "commerce.order_items"),
            columns=("commerce.orders.order_id", "commerce.order_items.order_id"),
            functions=("count",),
        ),
        draft=draft(
            sql="SELECT count(orders.order_id) AS order_count "
            "FROM commerce.orders JOIN commerce.order_items USING (order_id)",
            tables=("commerce.orders", "commerce.order_items"),
            columns=("commerce.orders.order_id", "commerce.order_items.order_id"),
        ),
        rows=({"order_count": 14},),
        columns=(QueryResultColumn("order_count"),),
    )

    amplification = signal(signals, "possible_duplicate_amplification")
    assert amplification.status == "warning"
    assert amplification.evidence["relationships"][0]["parent_table"] == "commerce.orders"


def test_duplicate_amplification_resists_false_positive_when_distinct_is_present() -> None:
    signals = validate(
        question="Count distinct orders by product",
        metadata=metadata(
            tables=("commerce.orders", "commerce.order_items"),
            columns=("commerce.orders.order_id", "commerce.order_items.order_id"),
            functions=("count",),
        ),
        draft=draft(
            sql="SELECT count(DISTINCT orders.order_id) AS order_count "
            "FROM commerce.orders JOIN commerce.order_items USING (order_id)",
            tables=("commerce.orders", "commerce.order_items"),
            columns=("commerce.orders.order_id", "commerce.order_items.order_id"),
        ),
        rows=({"order_count": 9},),
        columns=(QueryResultColumn("order_count"),),
    )

    assert signal(signals, "duplicate_amplification_distinct_present").status == "passed"


def test_aggregation_shape_warns_for_grouped_question_with_single_aggregate_row() -> None:
    signals = validate(
        question="Show order count by region",
        metadata=metadata(
            tables=("commerce.orders",),
            columns=("commerce.orders.order_id",),
            functions=("count",),
        ),
        rows=({"order_count": 9},),
        columns=(QueryResultColumn("order_count"),),
    )

    assert signal(signals, "aggregation_shape_mismatch").status == "warning"


def test_checks_degrade_gracefully_when_metadata_is_unavailable() -> None:
    signals = validate(metadata=None)

    assert signal(signals, "schema_coverage_unavailable").status == "unavailable"
    assert signal(signals, "generated_metadata_unavailable").status == "unavailable"
    assert signal(signals, "duplicate_amplification_metadata_unavailable").status == "unavailable"
    assert signal(signals, "aggregation_shape_metadata_unavailable").status == "unavailable"


def validate(
    question: str = "Show gross revenue",
    retrieval: SchemaRetrievalResult | None = None,
    metadata: SQLValidationMetadata | None = None,
    draft: SQLGenerationDraft | None = None,
    rows: tuple[dict[str, object], ...] = ({"gross_revenue": 100},),
    columns: tuple[QueryResultColumn, ...] = (QueryResultColumn("gross_revenue"),),
) -> tuple[ValidationSignal, ...]:
    execution = QueryExecutionResult(
        executed_sql=(draft or globals()["draft"]()).result.sql or "",
        columns=columns,
        rows=rows,
        row_count=len(rows),
        execution_duration_ms=1,
        truncated=False,
        plan=QueryPlanSummary(
            estimated_rows=len(rows),
            total_cost=1.0,
            plan_nodes=("Result",),
            referenced_relations=(),
        ),
        guardrail_metadata=metadata,
    )
    return DeterministicValidationService(Settings(environment="test")).validate(
        DeterministicValidationRequest(
            question=question,
            catalog=catalog(),
            draft=draft or globals()["draft"](),
            execution=execution,
            retrieval=retrieval,
        )
    )


def signal(signals: tuple[ValidationSignal, ...], code: str) -> ValidationSignal:
    for item in signals:
        if item.code == code:
            return item
    raise AssertionError(f"missing signal {code}: {[item.code for item in signals]}")


def metadata(
    tables: tuple[str, ...] = ("commerce.orders",),
    columns: tuple[str, ...] = ("commerce.orders.total_cents",),
    functions: tuple[str, ...] = (),
) -> SQLValidationMetadata:
    return SQLValidationMetadata(
        statement_type="select",
        referenced_tables=tuple(
            ReferencedTable(schema_name=table_id.split(".")[0], name=table_id.split(".")[1])
            for table_id in tables
        ),
        referenced_columns=tuple(
            ReferencedColumn(
                name=column_id.split(".")[2],
                source_name=column_id.split(".")[1],
                table_identifier=".".join(column_id.split(".")[:2]),
            )
            for column_id in columns
        ),
        functions=functions,
    )


def retrieval(tables: tuple[str, ...], columns: tuple[str, ...]) -> SchemaRetrievalResult:
    return SchemaRetrievalResult(
        question="Show gross revenue",
        strategy="lexical",
        ranked_tables=tuple(
            RankedTable(
                identifier=table_id,
                schema_name=table_id.split(".")[0],
                table_name=table_id.split(".")[1],
                score=10.0,
                reasons=(),
                selected=True,
            )
            for table_id in tables
        ),
        ranked_columns=tuple(
            RankedColumn(
                table_identifier=".".join(column_id.split(".")[:2]),
                column_name=column_id.split(".")[2],
                score=8.0,
                reasons=(),
                selected=True,
            )
            for column_id in columns
        ),
        relationship_paths=(),
        glossary_terms=("gross revenue",),
    )


def draft(
    sql: str = "SELECT sum(orders.total_cents) AS gross_revenue FROM commerce.orders AS orders",
    tables: tuple[str, ...] = ("commerce.orders",),
    columns: tuple[str, ...] = ("commerce.orders.total_cents",),
) -> SQLGenerationDraft:
    return SQLGenerationDraft(
        result=SQLGenerationResult(
            sql=sql,
            explanation="Calculates a deterministic fixture query.",
            model_confidence=0.8,
            tables_used=list(tables),
            columns_used=list(columns),
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


def catalog() -> SchemaCatalog:
    return SchemaCatalog(
        database_schema=DatabaseSchema(
            schemas=("commerce",),
            tables=(
                table("orders", ("order_id", "total_cents", "ordered_at")),
                table(
                    "order_items",
                    ("order_item_id", "order_id", "line_total_cents"),
                    (
                        ForeignKeySchema(
                            "commerce",
                            "order_items",
                            ("order_id",),
                            "commerce",
                            "orders",
                            ("order_id",),
                        ),
                    ),
                ),
                table("payments", ("payment_id", "order_id", "amount_cents")),
            ),
        ),
        samples=(),
        glossary=BusinessGlossary(
            version=1,
            terms=(
                GlossaryTerm(
                    "gross revenue",
                    "Total order value before refunds.",
                    "sum(orders.total_cents)",
                    related_tables=("orders",),
                    related_columns=("orders.total_cents",),
                ),
            ),
        ),
        generated_at_epoch_seconds=0,
        cache_expires_at_epoch_seconds=0,
        refreshed=False,
    )


def table(
    name: str,
    column_names: tuple[str, ...],
    foreign_keys: tuple[ForeignKeySchema, ...] = (),
) -> TableSchema:
    return TableSchema(
        schema_name="commerce",
        name=name,
        columns=tuple(ColumnSchema(column_name, "TEXT", False) for column_name in column_names),
        primary_key=PrimaryKeySchema((column_names[0],), f"{name}_pkey"),
        foreign_keys=foreign_keys,
    )
