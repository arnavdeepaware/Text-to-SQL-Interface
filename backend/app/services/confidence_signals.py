from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.core.config import Settings
from app.domain.confidence import ValidationSignal
from app.domain.query_execution import QueryExecutionResult
from app.domain.schema import DatabaseSchema, ForeignKeySchema, TableSchema
from app.domain.schema_catalog import SchemaCatalog
from app.domain.schema_retrieval import SchemaRetrievalResult
from app.domain.sql_generation import SQLGenerationDraft
from app.domain.sql_guardrails import SQLValidationMetadata


@dataclass(frozen=True)
class DeterministicValidationRequest:
    """Inputs available after guarded execution for deterministic validation."""

    question: str
    catalog: SchemaCatalog
    draft: SQLGenerationDraft
    execution: QueryExecutionResult
    retrieval: SchemaRetrievalResult | None = None


class DeterministicValidationService:
    """Run deterministic semantic and result-shape checks without provider calls."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def validate(self, request: DeterministicValidationRequest) -> tuple[ValidationSignal, ...]:
        if not self._settings.deterministic_validation_enabled:
            return (
                ValidationSignal(
                    code="deterministic_validation_disabled",
                    status="not_applicable",
                    score=0.0,
                    explanation="Deterministic validation is disabled by configuration.",
                ),
            )

        return (
            schema_coverage_signal(request),
            generated_metadata_signal(request),
            negative_count_signal(request),
            percentage_bounds_signal(request, self._settings),
            date_range_signal(request, self._settings),
            null_heavy_signal(request, self._settings),
            duplicate_amplification_signal(request),
            empty_result_signal(request),
            aggregation_shape_signal(request),
        )


def schema_coverage_signal(request: DeterministicValidationRequest) -> ValidationSignal:
    metadata = request.execution.guardrail_metadata
    if metadata is None:
        return unavailable_signal(
            "schema_coverage_unavailable",
            "Schema coverage could not be evaluated because AST metadata is unavailable.",
        )
    if request.retrieval is None:
        return warning_signal(
            "schema_coverage_retrieval_unavailable",
            "Schema coverage is partially evaluated because retrieved schema context is "
            "unavailable.",
            {"actual_tables": sorted(actual_table_ids(metadata))},
        )

    actual_tables = actual_table_ids(metadata)
    actual_columns = actual_column_ids(metadata)
    retrieved_tables = {table.identifier for table in request.retrieval.selected_tables}
    retrieved_columns = {column.identifier for column in request.retrieval.selected_columns}
    bridge_tables = {
        table.identifier for table in request.retrieval.selected_tables if table.bridge
    }
    allowed_tables = retrieved_tables | bridge_tables

    unexplained_tables = actual_tables - allowed_tables
    explained_columns = {
        column_id
        for column_id in actual_columns
        if (
            table_identifier_for_column(column_id) in allowed_tables
            or column_id in retrieved_columns
        )
    }
    unexplained_columns = actual_columns - explained_columns

    evidence = {
        "retrieved_tables": sorted(retrieved_tables),
        "retrieved_columns": sorted(retrieved_columns),
        "actual_tables": sorted(actual_tables),
        "actual_columns": sorted(actual_columns),
        "unexplained_tables": sorted(unexplained_tables),
        "unexplained_columns": sorted(unexplained_columns),
    }
    if unexplained_tables or unexplained_columns:
        return warning_signal(
            "schema_coverage_gap",
            "Generated SQL references tables or columns not explained by retrieved schema context.",
            evidence,
        )
    return passed_signal(
        "schema_coverage_passed",
        "Generated SQL references are covered by retrieved schema context.",
        evidence,
    )


def generated_metadata_signal(request: DeterministicValidationRequest) -> ValidationSignal:
    metadata = request.execution.guardrail_metadata
    if metadata is None:
        return unavailable_signal(
            "generated_metadata_unavailable",
            "Generated metadata could not be compared because AST metadata is unavailable.",
        )

    actual_tables = actual_table_ids(metadata)
    actual_columns = actual_column_ids(metadata)
    generated_tables = set(request.draft.result.tables_used)
    generated_columns = set(request.draft.result.columns_used)

    table_mismatches = (actual_tables ^ generated_tables) - {""}
    actual_physical_columns = {
        column_id
        for column_id in actual_columns
        if "." in column_id and not column_id.startswith("cte.")
    }
    column_mismatches = (actual_physical_columns ^ generated_columns) - {""}

    evidence = {
        "generated_tables": sorted(generated_tables),
        "generated_columns": sorted(generated_columns),
        "actual_tables": sorted(actual_tables),
        "actual_columns": sorted(actual_physical_columns),
        "table_mismatches": sorted(table_mismatches),
        "column_mismatches": sorted(column_mismatches),
    }
    if table_mismatches or column_mismatches:
        return warning_signal(
            "generated_metadata_mismatch",
            "Provider-declared metadata differs from AST-derived SQL references.",
            evidence,
        )
    return passed_signal(
        "generated_metadata_matches_ast",
        "Provider-declared metadata matches AST-derived SQL references.",
        evidence,
    )


def negative_count_signal(request: DeterministicValidationRequest) -> ValidationSignal:
    count_columns = count_like_columns(request)
    negatives = [
        {"column": column, "value": value}
        for row in request.execution.rows
        for column, value in row.items()
        if column in count_columns and is_number(value) and float(value) < 0
    ]
    if negatives:
        return failed_signal(
            "negative_count_detected",
            "Result contains a negative value in a count-like column.",
            {"negative_values": negatives},
        )
    if not count_columns:
        return not_applicable_signal(
            "negative_count_not_applicable",
            "No count-like result columns were present.",
        )
    return passed_signal(
        "negative_count_passed",
        "Count-like result columns did not contain negative values.",
        {"count_columns": sorted(count_columns)},
    )


def percentage_bounds_signal(
    request: DeterministicValidationRequest,
    settings: Settings,
) -> ValidationSignal:
    percent_columns = {
        column.name
        for column in request.execution.columns
        if is_percentage_column(column.name)
    }
    out_of_bounds = [
        {"column": column, "value": value}
        for row in request.execution.rows
        for column, value in row.items()
        if column in percent_columns
        and is_number(value)
        and (
            float(value) < settings.result_sanity_min_percentage
            or float(value) > settings.result_sanity_max_percentage
        )
    ]
    if out_of_bounds:
        return failed_signal(
            "percentage_out_of_bounds",
            "Result contains a percentage outside configured bounds.",
            {
                "out_of_bounds_values": out_of_bounds,
                "min_percentage": settings.result_sanity_min_percentage,
                "max_percentage": settings.result_sanity_max_percentage,
            },
        )
    if not percent_columns:
        return not_applicable_signal(
            "percentage_bounds_not_applicable",
            "No percentage-like result columns were present.",
        )
    return passed_signal(
        "percentage_bounds_passed",
        "Percentage-like result columns were within configured bounds.",
        {"percentage_columns": sorted(percent_columns)},
    )


def date_range_signal(
    request: DeterministicValidationRequest,
    settings: Settings,
) -> ValidationSignal:
    min_date = parse_date(settings.result_sanity_min_date)
    max_date = parse_date(settings.result_sanity_max_date)
    if min_date is None or max_date is None:
        return warning_signal(
            "date_range_configuration_unavailable",
            "Date range validation could not run because configured date bounds are invalid.",
            {
                "min_date": settings.result_sanity_min_date,
                "max_date": settings.result_sanity_max_date,
            },
        )

    date_columns = {
        column.name for column in request.execution.columns if is_date_column(column.name)
    }
    outside = []
    for row in request.execution.rows:
        for column, value in row.items():
            if column not in date_columns:
                continue
            parsed = parse_result_date(value)
            if parsed is not None and (parsed < min_date or parsed > max_date):
                outside.append({"column": column, "value": str(value)})

    if outside:
        return warning_signal(
            "date_outside_configured_range",
            "Result contains dates outside configured database date bounds.",
            {
                "outside_values": outside,
                "min_date": min_date.isoformat(),
                "max_date": max_date.isoformat(),
            },
        )
    if not date_columns:
        return not_applicable_signal(
            "date_range_not_applicable",
            "No date-like result columns were present.",
        )
    return passed_signal(
        "date_range_passed",
        "Date-like result values were within configured database date bounds.",
        {
            "date_columns": sorted(date_columns),
            "min_date": min_date.isoformat(),
            "max_date": max_date.isoformat(),
        },
    )


def null_heavy_signal(
    request: DeterministicValidationRequest,
    settings: Settings,
) -> ValidationSignal:
    rows = request.execution.rows
    if not rows:
        return not_applicable_signal(
            "null_heavy_not_applicable",
            "NULL-heavy output checks do not apply to empty results.",
        )

    null_heavy_columns = []
    for column in request.execution.columns:
        null_count = sum(1 for row in rows if row.get(column.name) is None)
        ratio = null_count / len(rows)
        if ratio >= settings.result_sanity_null_heavy_threshold:
            null_heavy_columns.append({"column": column.name, "null_ratio": ratio})

    if null_heavy_columns:
        return warning_signal(
            "null_heavy_output_column",
            "One or more output columns are NULL-heavy under the configured threshold.",
            {
                "columns": null_heavy_columns,
                "threshold": settings.result_sanity_null_heavy_threshold,
            },
        )
    return passed_signal(
        "null_heavy_passed",
        "Output columns were not NULL-heavy under the configured threshold.",
        {"threshold": settings.result_sanity_null_heavy_threshold},
    )


def duplicate_amplification_signal(request: DeterministicValidationRequest) -> ValidationSignal:
    metadata = request.execution.guardrail_metadata
    if metadata is None:
        return unavailable_signal(
            "duplicate_amplification_metadata_unavailable",
            "Duplicate amplification could not be evaluated because AST metadata is unavailable.",
        )
    if "count" not in metadata.functions:
        return not_applicable_signal(
            "duplicate_amplification_not_applicable",
            "No COUNT aggregate was present.",
        )

    referenced_tables = actual_table_ids(metadata)
    one_to_many_paths = [
        path
        for path in one_to_many_relationships(request.catalog.database_schema)
        if path["parent_table"] in referenced_tables and path["child_table"] in referenced_tables
    ]
    if not one_to_many_paths:
        return passed_signal(
            "duplicate_amplification_passed",
            "COUNT aggregate does not span known one-to-many schema relationships.",
            {"referenced_tables": sorted(referenced_tables)},
        )

    sql = request.draft.result.sql or ""
    if "distinct" in sql.casefold():
        return passed_signal(
            "duplicate_amplification_distinct_present",
            "COUNT aggregate spans one-to-many relationships with DISTINCT present.",
            {"relationships": one_to_many_paths},
        )

    return warning_signal(
        "possible_duplicate_amplification",
        "COUNT aggregate spans known one-to-many relationships without visible DISTINCT.",
        {"relationships": one_to_many_paths},
    )


def empty_result_signal(request: DeterministicValidationRequest) -> ValidationSignal:
    if request.execution.row_count > 0:
        return passed_signal(
            "empty_result_passed",
            "Query returned at least one row.",
            {"row_count": request.execution.row_count},
        )

    evidence: dict[str, Any] = {
        "row_count": request.execution.row_count,
        "retrieved_tables": []
        if request.retrieval is None
        else [table.identifier for table in request.retrieval.selected_tables],
    }
    return warning_signal(
        "unexpected_empty_result",
        "Query returned no rows; deterministic validation cannot prove whether the empty result "
        "is expected.",
        evidence,
    )


def aggregation_shape_signal(request: DeterministicValidationRequest) -> ValidationSignal:
    metadata = request.execution.guardrail_metadata
    if metadata is None:
        return unavailable_signal(
            "aggregation_shape_metadata_unavailable",
            "Aggregation shape could not be evaluated because AST metadata is unavailable.",
        )

    question = f" {request.question.casefold()} "
    aggregate_functions = sorted(
        function for function in metadata.functions if function in AGGREGATES
    )
    count_columns = count_like_columns(request)
    issues: list[str] = []
    if " count " in question and not aggregate_functions and not count_columns:
        issues.append("question_mentions_count_without_count_signal")
    if " by " in question and aggregate_functions and len(request.execution.rows) <= 1:
        issues.append("grouped_question_returned_single_aggregate_row")

    evidence = {
        "aggregate_functions": aggregate_functions,
        "count_columns": sorted(count_columns),
        "row_count": request.execution.row_count,
        "issues": issues,
    }
    if issues:
        return warning_signal(
            "aggregation_shape_mismatch",
            "Result shape may not match the requested aggregation grain.",
            evidence,
        )
    if not aggregate_functions and not count_columns:
        return not_applicable_signal(
            "aggregation_shape_not_applicable",
            "No aggregate intent or aggregate output was detected.",
            evidence,
        )
    return passed_signal(
        "aggregation_shape_passed",
        "Aggregate result shape is consistent with available deterministic evidence.",
        evidence,
    )


def actual_table_ids(metadata: SQLValidationMetadata) -> set[str]:
    return {
        table.identifier
        for table in metadata.referenced_tables
        if table.source == "table" and table.schema_name is not None
    }


def actual_column_ids(metadata: SQLValidationMetadata) -> set[str]:
    return {
        column.identifier
        for column in metadata.referenced_columns
        if column.table_identifier is not None
    }


def table_identifier_for_column(column_id: str) -> str:
    parts = column_id.split(".")
    if len(parts) < 3:
        return ""
    return ".".join(parts[:2])


def one_to_many_relationships(database_schema: DatabaseSchema) -> list[dict[str, str]]:
    tables = {table.identifier: table for table in database_schema.tables}
    relationships: list[dict[str, str]] = []
    for table in database_schema.tables:
        for foreign_key in table.foreign_keys:
            parent = tables.get(foreign_key.referred_table_identifier)
            if parent is None:
                continue
            if tuple(foreign_key.referred_columns) == tuple(parent.primary_key.columns):
                relationships.append(relationship_evidence(table, parent, foreign_key))
    return relationships


def relationship_evidence(
    child: TableSchema,
    parent: TableSchema,
    foreign_key: ForeignKeySchema,
) -> dict[str, str]:
    return {
        "parent_table": parent.identifier,
        "child_table": child.identifier,
        "foreign_key": foreign_key.display_path,
    }


def count_like_columns(request: DeterministicValidationRequest) -> set[str]:
    return {
        column.name
        for column in request.execution.columns
        if "count" in column.name.casefold() or column.name.casefold().endswith("_cnt")
    }


def is_percentage_column(column_name: str) -> bool:
    normalized = column_name.casefold()
    return "percent" in normalized or normalized.endswith("_pct") or normalized == "pct"


def is_date_column(column_name: str) -> bool:
    normalized = column_name.casefold()
    return (
        "date" in normalized
        or normalized.endswith("_at")
        or normalized.endswith("_day")
        or normalized.endswith("_month")
        or normalized.endswith("_year")
    )


def is_number(value: object) -> bool:
    return isinstance(value, int | float | Decimal) and not isinstance(value, bool)


def parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def parse_result_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return date.fromisoformat(value)
            except ValueError:
                return None
    return None


def passed_signal(
    code: str,
    explanation: str,
    evidence: dict[str, Any] | None = None,
) -> ValidationSignal:
    return ValidationSignal(code, "passed", 1.0, explanation, evidence or {})


def warning_signal(
    code: str,
    explanation: str,
    evidence: dict[str, Any] | None = None,
) -> ValidationSignal:
    return ValidationSignal(code, "warning", 0.5, explanation, evidence or {})


def failed_signal(
    code: str,
    explanation: str,
    evidence: dict[str, Any] | None = None,
) -> ValidationSignal:
    return ValidationSignal(code, "failed", 0.0, explanation, evidence or {})


def unavailable_signal(
    code: str,
    explanation: str,
    evidence: dict[str, Any] | None = None,
) -> ValidationSignal:
    return ValidationSignal(code, "unavailable", 0.0, explanation, evidence or {})


def not_applicable_signal(
    code: str,
    explanation: str,
    evidence: dict[str, Any] | None = None,
) -> ValidationSignal:
    return ValidationSignal(code, "not_applicable", 0.0, explanation, evidence or {})


AGGREGATES = frozenset({"avg", "count", "max", "min", "sum"})
