from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping
from time import perf_counter
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import DBAPIError, OperationalError, SQLAlchemyError

from app.core.config import Settings
from app.domain.query_execution import (
    QueryExecutionResult,
    QueryPlanAudit,
    QueryPlanInspection,
    QueryPlanSummary,
    QueryResultColumn,
)
from app.domain.schema_catalog import SchemaCatalog
from app.domain.sql_guardrails import SQLValidationResult
from app.services.sql_guardrails import GeneratedSQLValidator, SQLGuardrailValidationError

logger = logging.getLogger(__name__)


class QueryPlanInspectionError(RuntimeError):
    """Base error for fail-closed EXPLAIN inspection failures."""

    public_code = "sql_guardrail_plan_error"
    public_message = "Generated SQL could not be safely planned."


class QueryPlanTimeoutError(QueryPlanInspectionError):
    public_code = "sql_guardrail_explain_timeout"
    public_message = "Generated SQL planning timed out."


class QueryPlanThresholdExceededError(QueryPlanInspectionError):
    public_code = "sql_guardrail_plan_too_expensive"
    public_message = "Generated SQL exceeded planning safety limits."


class QueryPlanReferenceMismatchError(QueryPlanInspectionError):
    public_code = "sql_guardrail_plan_reference_mismatch"
    public_message = "Generated SQL plan referenced unexpected relations."


class QueryExecutionError(RuntimeError):
    """Base error for fail-closed read-only execution failures."""

    public_code = "sql_execution_error"
    public_message = "Generated SQL execution failed."


class QueryExecutionTimeoutError(QueryExecutionError):
    public_code = "sql_execution_timeout"
    public_message = "Generated SQL execution timed out."


class QueryExecutionDatabaseUnavailableError(QueryExecutionError):
    public_code = "database_unavailable"
    public_message = "The database is unavailable."


class QueryExecutionService:
    """Validate, plan, and execute generated SQL in a read-only transaction."""

    def __init__(
        self,
        engine: Engine,
        settings: Settings,
        validator: GeneratedSQLValidator | None = None,
    ) -> None:
        self._engine = engine
        self._settings = settings
        self._validator = validator or GeneratedSQLValidator(settings)

    def execute(self, sql: str, catalog: SchemaCatalog) -> QueryExecutionResult:
        validation = self._validator.validate(sql, catalog)
        if not validation.valid:
            raise SQLGuardrailValidationError(validation)

        started = perf_counter()
        transaction = None
        try:
            with self._engine.connect() as connection:
                transaction = connection.begin()
                try:
                    configure_read_only_transaction(connection, self._settings)
                    plan = self._inspect_plan(connection, validation)
                    execution_result = connection.exec_driver_sql(validation.sql)
                    rows = fetch_bounded_rows(
                        execution_result,
                        self._settings.sql_execution_max_rows,
                    )
                    columns = result_columns(execution_result)
                    truncated = len(rows) > self._settings.sql_execution_max_rows
                    returned_rows = rows[: self._settings.sql_execution_max_rows]
                    result = QueryExecutionResult(
                        executed_sql=validation.sql,
                        columns=columns,
                        rows=tuple(returned_rows),
                        row_count=len(returned_rows),
                        execution_duration_ms=elapsed_ms(started),
                        truncated=truncated,
                        plan=plan.summary,
                        guardrail_findings=validation.findings,
                        guardrail_metadata=validation.metadata,
                    )
                    log_execution_decision("executed", validation, result.plan, result)
                    return result
                finally:
                    if transaction.is_active:
                        transaction.rollback()
        except QueryPlanInspectionError:
            raise
        except SQLAlchemyError as exc:
            raise mapped_execution_error(exc) from exc
        finally:
            if transaction is not None and transaction.is_active:
                transaction.rollback()

    def _inspect_plan(
        self,
        connection: Any,
        validation: SQLValidationResult,
    ) -> QueryPlanInspection:
        try:
            connection.execute(
                text(
                    "SET LOCAL statement_timeout = "
                    f"{self._settings.sql_guardrail_explain_timeout_ms}"
                )
            )
            raw_plan = connection.exec_driver_sql(
                f"EXPLAIN (FORMAT JSON, COSTS TRUE, VERBOSE TRUE) {validation.sql}"
            ).scalar_one()
        except SQLAlchemyError as exc:
            if is_timeout_error(exc):
                log_execution_decision("plan_timeout", validation, None, None)
                raise QueryPlanTimeoutError("EXPLAIN timed out") from exc
            raise QueryPlanInspectionError("EXPLAIN failed") from exc

        try:
            summary = parse_plan_summary(raw_plan)
        except (TypeError, ValueError, KeyError) as exc:
            raise QueryPlanInspectionError("EXPLAIN returned an unsupported JSON shape") from exc

        try:
            enforce_plan_thresholds(summary, self._settings)
            ensure_plan_references_were_validated(summary, validation)
        except QueryPlanInspectionError:
            log_execution_decision("plan_blocked", validation, summary, None)
            raise
        connection.execute(
            text(f"SET LOCAL statement_timeout = {self._settings.database_statement_timeout_ms}")
        )
        log_execution_decision("planned", validation, summary, None)
        return QueryPlanInspection(summary=summary, audit=QueryPlanAudit(summary, raw_plan))


def configure_read_only_transaction(connection: Any, settings: Settings) -> None:
    connection.execute(text("SET TRANSACTION READ ONLY"))
    connection.execute(text(f"SET LOCAL lock_timeout = {settings.sql_execution_lock_timeout_ms}"))
    connection.execute(
        text(
            "SET LOCAL idle_in_transaction_session_timeout = "
            f"{settings.database_statement_timeout_ms}"
        )
    )


def parse_plan_summary(raw_plan: Any) -> QueryPlanSummary:
    plan_payload = json.loads(raw_plan) if isinstance(raw_plan, str) else raw_plan
    if not isinstance(plan_payload, list) or not plan_payload:
        raise ValueError("EXPLAIN JSON must be a non-empty list")

    root_item = plan_payload[0]
    if not isinstance(root_item, Mapping):
        raise ValueError("EXPLAIN JSON root item must be an object")
    plan = root_item["Plan"]
    if not isinstance(plan, Mapping):
        raise ValueError("EXPLAIN JSON Plan must be an object")

    estimated_rows = plan["Plan Rows"]
    total_cost = plan["Total Cost"]
    if not isinstance(estimated_rows, int):
        raise ValueError("Plan Rows must be an integer")
    if not isinstance(total_cost, int | float):
        raise ValueError("Total Cost must be numeric")

    nodes: list[str] = []
    relations: list[str] = []
    collect_plan_facts(plan, nodes, relations)
    return QueryPlanSummary(
        estimated_rows=estimated_rows,
        total_cost=float(total_cost),
        plan_nodes=tuple(deduplicate(nodes)),
        referenced_relations=tuple(deduplicate(relations)),
    )


def collect_plan_facts(
    plan: Mapping[str, Any],
    nodes: list[str],
    relations: list[str],
) -> None:
    node_type = plan.get("Node Type")
    if isinstance(node_type, str) and node_type:
        nodes.append(node_type)

    relation_name = plan.get("Relation Name")
    if isinstance(relation_name, str) and relation_name:
        schema_name = plan.get("Schema")
        if isinstance(schema_name, str) and schema_name:
            relations.append(f"{schema_name}.{relation_name}")
        else:
            relations.append(relation_name)

    child_plans = plan.get("Plans") or ()
    if isinstance(child_plans, Iterable):
        for child in child_plans:
            if isinstance(child, Mapping):
                collect_plan_facts(child, nodes, relations)


def enforce_plan_thresholds(summary: QueryPlanSummary, settings: Settings) -> None:
    if (
        summary.estimated_rows > settings.sql_guardrail_max_plan_rows
        or summary.total_cost > settings.sql_guardrail_max_plan_total_cost
    ):
        raise QueryPlanThresholdExceededError("EXPLAIN plan exceeded configured thresholds")


def ensure_plan_references_were_validated(
    summary: QueryPlanSummary,
    validation: SQLValidationResult,
) -> None:
    allowed_relations = {
        table.identifier
        for table in validation.metadata.referenced_tables
        if table.source == "table"
    }
    allowed_relations.update(
        table.name
        for table in validation.metadata.referenced_tables
        if table.source == "table"
    )

    unexpected = tuple(
        relation
        for relation in summary.referenced_relations
        if relation not in allowed_relations
    )
    if unexpected:
        raise QueryPlanReferenceMismatchError("EXPLAIN plan referenced unexpected relations")


def fetch_bounded_rows(result: CursorResult[Any], max_rows: int) -> list[dict[str, Any]]:
    return [dict(row) for row in result.mappings().fetchmany(max_rows + 1)]


def result_columns(result: CursorResult[Any]) -> tuple[QueryResultColumn, ...]:
    keys = tuple(str(key) for key in result.keys())
    description = getattr(getattr(result, "cursor", None), "description", None)
    columns: list[QueryResultColumn] = []
    for index, key in enumerate(keys):
        columns.append(QueryResultColumn(name=key, type_code=column_type_code(description, index)))
    return tuple(columns)


def column_type_code(description: object, index: int) -> str | None:
    if not isinstance(description, tuple | list) or index >= len(description):
        return None
    item = description[index]
    type_code = getattr(item, "type_code", None)
    if type_code is None and isinstance(item, tuple) and len(item) > 1:
        type_code = item[1]
    if type_code is None:
        return None
    return str(type_code)


def mapped_execution_error(exc: SQLAlchemyError) -> QueryExecutionError:
    if is_timeout_error(exc):
        return QueryExecutionTimeoutError("Generated SQL execution timed out")
    if isinstance(exc, OperationalError) or (
        isinstance(exc, DBAPIError) and exc.connection_invalidated
    ):
        return QueryExecutionDatabaseUnavailableError("Database unavailable during execution")
    return QueryExecutionError("Generated SQL execution failed")


def is_timeout_error(exc: BaseException) -> bool:
    visited: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        message = str(current).lower()
        error_name = type(current).__name__.lower()
        if (
            "statement timeout" in message
            or "canceling statement due to statement timeout" in message
            or "timeout expired" in message
            or "querycanceled" in error_name
        ):
            return True
        current = getattr(current, "orig", None) or current.__cause__ or current.__context__
    return False


def elapsed_ms(started: float) -> int:
    return max(0, round((perf_counter() - started) * 1000))


def deduplicate(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def log_execution_decision(
    outcome: str,
    validation: SQLValidationResult,
    plan: QueryPlanSummary | None,
    result: QueryExecutionResult | None,
) -> None:
    logger.info(
        "Generated SQL execution decision",
        extra={
            "outcome": outcome,
            "referenced_tables": [
                table.identifier
                for table in validation.metadata.referenced_tables
                if table.source == "table"
            ],
            "effective_limit": validation.metadata.effective_limit,
            "plan_estimated_rows": None if plan is None else plan.estimated_rows,
            "plan_total_cost": None if plan is None else plan.total_cost,
            "plan_nodes": [] if plan is None else list(plan.plan_nodes),
            "result_row_count": None if result is None else result.row_count,
            "result_truncated": None if result is None else result.truncated,
        },
    )
