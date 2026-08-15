from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from app.domain.evaluation import ExpectedResult
from app.domain.query_execution import QueryExecutionResult


@dataclass(frozen=True)
class ResultMatch:
    matched: bool
    reason: str


def compare_expected_result(expected: ExpectedResult, actual: QueryExecutionResult) -> ResultMatch:
    """Compare a seeded expected result without making SQL text the oracle."""

    if actual.truncated:
        return ResultMatch(False, "actual_result_truncated")
    actual_columns = [column.name.casefold() for column in actual.columns]
    expected_columns = [column.casefold() for column in expected.columns]
    if actual_columns != expected_columns:
        return ResultMatch(False, "column_mismatch")
    expected_rows = [canonical_row(row, expected_columns) for row in expected.rows]
    actual_rows = [canonical_row(row, expected_columns) for row in actual.rows]
    if None in expected_rows or None in actual_rows:
        return ResultMatch(False, "unsupported_result_value")
    if expected.ordered:
        return ResultMatch(
            expected_rows == actual_rows,
            "matched" if expected_rows == actual_rows else "ordered_row_mismatch",
        )
    return ResultMatch(
        Counter(expected_rows) == Counter(actual_rows),
        "matched" if Counter(expected_rows) == Counter(actual_rows) else "row_mismatch",
    )


def canonical_row(row: dict[str, Any], columns: list[str]) -> tuple[Any, ...] | None:
    normalized = {key.casefold(): canonical_value(value) for key, value in row.items()}
    if not set(columns) <= set(normalized) or any(
        value is _UNSUPPORTED for value in normalized.values()
    ):
        return None
    return tuple(normalized[column] for column in columns)


def canonical_value(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return _UNSUPPORTED
    if isinstance(value, Decimal):
        return value.normalize()
    return _UNSUPPORTED


class _Unsupported:
    pass


_UNSUPPORTED = _Unsupported()
