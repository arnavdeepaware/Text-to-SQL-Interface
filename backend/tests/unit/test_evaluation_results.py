from app.domain.evaluation import ExpectedResult
from app.domain.query_execution import QueryExecutionResult, QueryPlanSummary, QueryResultColumn
from app.services.evaluation_results import compare_expected_result


def test_result_comparison_is_row_order_independent_by_default() -> None:
    expected = ExpectedResult(
        columns=["status", "order_count"],
        rows=[{"status": "cancelled", "order_count": 2}, {"status": "delivered", "order_count": 5}],
    )
    actual = execution(
        columns=(QueryResultColumn("status"), QueryResultColumn("order_count")),
        rows=({"status": "delivered", "order_count": 5}, {"status": "cancelled", "order_count": 2}),
    )

    comparison = compare_expected_result(expected, actual)

    assert comparison.matched is True
    assert comparison.reason == "matched"


def test_result_comparison_honors_order_when_requested() -> None:
    expected = ExpectedResult(
        columns=["order_id"],
        rows=[{"order_id": 1}, {"order_id": 2}],
        ordered=True,
    )
    actual = execution(
        columns=(QueryResultColumn("order_id"),),
        rows=({"order_id": 2}, {"order_id": 1}),
    )

    comparison = compare_expected_result(expected, actual)

    assert comparison.matched is False
    assert comparison.reason == "ordered_row_mismatch"


def test_result_comparison_rejects_truncated_results() -> None:
    expected = ExpectedResult(columns=["order_id"], rows=[{"order_id": 1}])
    actual = QueryExecutionResult(
        executed_sql="SELECT 1",
        columns=(QueryResultColumn("order_id"),),
        rows=({"order_id": 1},),
        row_count=1,
        execution_duration_ms=1,
        truncated=True,
        plan=QueryPlanSummary(
            estimated_rows=1,
            total_cost=1.0,
            plan_nodes=("Result",),
            referenced_relations=(),
        ),
    )

    comparison = compare_expected_result(expected, actual)

    assert comparison.matched is False
    assert comparison.reason == "actual_result_truncated"


def execution(
    columns: tuple[QueryResultColumn, ...], rows: tuple[dict[str, object], ...]
) -> QueryExecutionResult:
    return QueryExecutionResult(
        executed_sql="SELECT 1",
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
