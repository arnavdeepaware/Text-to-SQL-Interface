from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from app.core.config import Settings
from app.domain.query_execution import QueryExecutionResult

ResultComparisonOutcome = Literal["agreement", "disagreement", "incomparable"]


@dataclass(frozen=True)
class ResultComparison:
    """Public-safe semantic comparison of two guarded result sets."""

    outcome: ResultComparisonOutcome
    code: str
    explanation: str
    evidence: dict[str, Any]


def compare_result_sets(
    primary: QueryExecutionResult,
    secondary: QueryExecutionResult,
    settings: Settings,
) -> ResultComparison:
    if primary.truncated or secondary.truncated:
        return incomparable(
            "result_comparison_truncated",
            "Result sets cannot be compared because at least one result was truncated.",
            primary,
            secondary,
            settings,
        )
    if (
        primary.row_count > settings.confidence_multi_query_max_result_rows
        or secondary.row_count > settings.confidence_multi_query_max_result_rows
    ):
        return incomparable(
            "result_comparison_too_many_rows",
            "Result sets exceed the configured comparison row limit.",
            primary,
            secondary,
            settings,
        )

    primary_columns = normalized_columns(primary)
    secondary_columns = normalized_columns(secondary)
    if primary_columns is None or secondary_columns is None:
        return incomparable(
            "result_comparison_duplicate_columns",
            "Result sets contain duplicate column names after normalization.",
            primary,
            secondary,
            settings,
        )
    if set(primary_columns) != set(secondary_columns):
        return incomparable(
            "result_comparison_column_mismatch",
            "Result sets expose different normalized column names.",
            primary,
            secondary,
            settings,
        )
    comparison_columns = tuple(sorted(primary_columns))

    if primary.row_count != secondary.row_count:
        return disagreement(
            "result_comparison_row_count_mismatch",
            "Result sets returned different row counts.",
            primary,
            secondary,
            settings,
            {"comparison_columns": comparison_columns},
        )

    primary_rows = normalize_rows(primary, comparison_columns)
    secondary_rows = normalize_rows(secondary, comparison_columns)
    if primary_rows is None or secondary_rows is None:
        return incomparable(
            "result_comparison_unsupported_value",
            "Result sets contain values that cannot be normalized safely.",
            primary,
            secondary,
            settings,
            {"comparison_columns": comparison_columns},
        )

    unmatched_secondary = list(secondary_rows)
    for primary_row in primary_rows:
        match_index = matching_row_index(primary_row, unmatched_secondary, settings)
        if match_index is None:
            return disagreement(
                "result_comparison_value_mismatch",
                "Result sets differ after row-order-independent normalization.",
                primary,
                secondary,
                settings,
                {"comparison_columns": comparison_columns},
            )
        unmatched_secondary.pop(match_index)

    return ResultComparison(
        outcome="agreement",
        code="result_sets_agree",
        explanation="Result sets match after row-order-independent normalization.",
        evidence=base_evidence(primary, secondary, settings)
        | {"comparison_columns": comparison_columns},
    )


def normalized_columns(execution: QueryExecutionResult) -> tuple[str, ...] | None:
    names = tuple(column.name.casefold() for column in execution.columns)
    if len(names) != len(set(names)):
        return None
    return names


def normalize_rows(
    execution: QueryExecutionResult,
    comparison_columns: tuple[str, ...],
) -> tuple[tuple[Any, ...], ...] | None:
    normalized_rows: list[tuple[Any, ...]] = []
    for row in execution.rows:
        normalized_row = {key.casefold(): value for key, value in row.items()}
        if not set(comparison_columns) <= set(normalized_row):
            return None
        values: list[Any] = []
        for column in comparison_columns:
            value = normalized_value(normalized_row[column])
            if value is UNSUPPORTED_VALUE:
                return None
            values.append(value)
        normalized_rows.append(tuple(values))
    return tuple(normalized_rows)


def normalized_value(value: Any) -> Any:
    if value is None or isinstance(value, str | bool | int | Decimal):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return UNSUPPORTED_VALUE
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return UNSUPPORTED_VALUE


def matching_row_index(
    row: tuple[Any, ...],
    candidates: list[tuple[Any, ...]],
    settings: Settings,
) -> int | None:
    for index, candidate in enumerate(candidates):
        if rows_equal(row, candidate, settings):
            return index
    return None


def rows_equal(left: tuple[Any, ...], right: tuple[Any, ...], settings: Settings) -> bool:
    if len(left) != len(right):
        return False
    return all(values_equal(a, b, settings) for a, b in zip(left, right, strict=True))


def values_equal(left: Any, right: Any, settings: Settings) -> bool:
    if isinstance(left, Decimal) or isinstance(right, Decimal):
        if not isinstance(left, int | float | Decimal) or isinstance(left, bool):
            return False
        if not isinstance(right, int | float | Decimal) or isinstance(right, bool):
            return False
        try:
            difference = abs(Decimal(str(left)) - Decimal(str(right)))
            tolerance = Decimal(str(settings.confidence_multi_query_decimal_abs_tol))
        except InvalidOperation:
            return False
        return difference <= tolerance
    if isinstance(left, float) or isinstance(right, float):
        if not isinstance(left, int | float | Decimal) or isinstance(left, bool):
            return False
        if not isinstance(right, int | float | Decimal) or isinstance(right, bool):
            return False
        return math.isclose(
            float(left),
            float(right),
            rel_tol=settings.confidence_multi_query_float_rel_tol,
            abs_tol=settings.confidence_multi_query_float_abs_tol,
        )
    return bool(left == right)


def incomparable(
    code: str,
    explanation: str,
    primary: QueryExecutionResult,
    secondary: QueryExecutionResult,
    settings: Settings,
    extra: dict[str, Any] | None = None,
) -> ResultComparison:
    return ResultComparison(
        outcome="incomparable",
        code=code,
        explanation=explanation,
        evidence=base_evidence(primary, secondary, settings) | (extra or {}),
    )


def disagreement(
    code: str,
    explanation: str,
    primary: QueryExecutionResult,
    secondary: QueryExecutionResult,
    settings: Settings,
    extra: dict[str, Any] | None = None,
) -> ResultComparison:
    return ResultComparison(
        outcome="disagreement",
        code=code,
        explanation=explanation,
        evidence=base_evidence(primary, secondary, settings) | (extra or {}),
    )


def base_evidence(
    primary: QueryExecutionResult,
    secondary: QueryExecutionResult,
    settings: Settings,
) -> dict[str, Any]:
    return {
        "primary_row_count": primary.row_count,
        "secondary_row_count": secondary.row_count,
        "primary_columns": [column.name for column in primary.columns],
        "secondary_columns": [column.name for column in secondary.columns],
        "decimal_abs_tol": settings.confidence_multi_query_decimal_abs_tol,
        "float_rel_tol": settings.confidence_multi_query_float_rel_tol,
        "float_abs_tol": settings.confidence_multi_query_float_abs_tol,
        "max_result_rows": settings.confidence_multi_query_max_result_rows,
    }


class _UnsupportedValue:
    pass


UNSUPPORTED_VALUE = _UnsupportedValue()
