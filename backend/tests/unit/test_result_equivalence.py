from __future__ import annotations

from decimal import Decimal

from app.core.config import Settings
from app.domain.query_execution import QueryExecutionResult, QueryPlanSummary, QueryResultColumn
from app.services.result_equivalence import compare_result_sets


def test_result_equivalence_ignores_row_order_and_tolerates_float_noise() -> None:
    primary = execution(
        columns=(QueryResultColumn("region"), QueryResultColumn("refund_rate")),
        rows=(
            {"region": "West", "refund_rate": 0.10000001},
            {"region": "East", "refund_rate": 0.2},
        ),
    )
    secondary = execution(
        columns=(QueryResultColumn("REFUND_RATE"), QueryResultColumn("REGION")),
        rows=(
            {"REFUND_RATE": 0.2, "REGION": "East"},
            {"REFUND_RATE": 0.10000002, "REGION": "West"},
        ),
    )

    comparison = compare_result_sets(primary, secondary, Settings(environment="test"))

    assert comparison.outcome == "agreement"
    assert comparison.code == "result_sets_agree"


def test_result_equivalence_uses_explicit_decimal_tolerance_for_monetary_values() -> None:
    settings = Settings(
        environment="test",
        confidence_multi_query_decimal_abs_tol=0.01,
    )
    primary = execution(
        columns=(QueryResultColumn("gross_revenue"),),
        rows=({"gross_revenue": Decimal("10.00")},),
    )
    secondary = execution(
        columns=(QueryResultColumn("gross_revenue"),),
        rows=({"gross_revenue": Decimal("10.005")},),
    )

    comparison = compare_result_sets(primary, secondary, settings)

    assert comparison.outcome == "agreement"
    assert comparison.evidence["decimal_abs_tol"] == 0.01


def test_result_equivalence_reports_decimal_values_outside_tolerance() -> None:
    settings = Settings(
        environment="test",
        confidence_multi_query_decimal_abs_tol=0.01,
    )
    primary = execution(
        columns=(QueryResultColumn("gross_revenue"),),
        rows=({"gross_revenue": Decimal("10.00")},),
    )
    secondary = execution(
        columns=(QueryResultColumn("gross_revenue"),),
        rows=({"gross_revenue": Decimal("10.02")},),
    )

    comparison = compare_result_sets(primary, secondary, settings)

    assert comparison.outcome == "disagreement"
    assert comparison.code == "result_comparison_value_mismatch"


def test_result_equivalence_preserves_duplicate_multiplicity() -> None:
    primary = execution(
        columns=(QueryResultColumn("order_id"),),
        rows=({"order_id": 1}, {"order_id": 1}),
    )
    secondary = execution(
        columns=(QueryResultColumn("order_id"),),
        rows=({"order_id": 1},),
    )

    comparison = compare_result_sets(primary, secondary, Settings(environment="test"))

    assert comparison.outcome == "disagreement"
    assert comparison.code == "result_comparison_row_count_mismatch"


def test_result_equivalence_reports_incomparable_for_column_mismatch() -> None:
    primary = execution(
        columns=(QueryResultColumn("gross_revenue"),),
        rows=({"gross_revenue": Decimal("10.00")},),
    )
    secondary = execution(
        columns=(QueryResultColumn("net_revenue"),),
        rows=({"net_revenue": Decimal("10.00")},),
    )

    comparison = compare_result_sets(primary, secondary, Settings(environment="test"))

    assert comparison.outcome == "incomparable"
    assert comparison.code == "result_comparison_column_mismatch"


def execution(
    columns: tuple[QueryResultColumn, ...],
    rows: tuple[dict[str, object], ...],
) -> QueryExecutionResult:
    return QueryExecutionResult(
        executed_sql="SELECT 1 LIMIT 1000",
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
    )
