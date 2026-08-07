from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

import pytest
from sqlalchemy import Engine

from app.core.config import Settings
from app.domain.glossary import BusinessGlossary
from app.domain.schema import ColumnSchema, DatabaseSchema, PrimaryKeySchema, TableSchema
from app.domain.schema_catalog import SchemaCatalog
from app.services.query_execution import (
    QueryExecutionService,
    QueryPlanThresholdExceededError,
    configure_read_only_transaction,
    enforce_plan_thresholds,
    parse_plan_summary,
)
from app.services.sql_guardrails import SQLGuardrailValidationError


def test_parse_plan_summary_from_postgresql_json_fixture() -> None:
    raw_plan = [
        {
            "Plan": {
                "Node Type": "Limit",
                "Plan Rows": 5,
                "Total Cost": 12.34,
                "Plans": [
                    {
                        "Node Type": "Nested Loop",
                        "Plan Rows": 5,
                        "Total Cost": 11.0,
                        "Plans": [
                            {
                                "Node Type": "Seq Scan",
                                "Relation Name": "orders",
                                "Schema": "commerce",
                            },
                            {
                                "Node Type": "Index Scan",
                                "Relation Name": "customers",
                                "Schema": "commerce",
                            },
                        ],
                    }
                ],
            }
        }
    ]

    summary = parse_plan_summary(raw_plan)

    assert summary.estimated_rows == 5
    assert summary.total_cost == 12.34
    assert summary.plan_nodes == ("Limit", "Nested Loop", "Seq Scan", "Index Scan")
    assert summary.referenced_relations == ("commerce.orders", "commerce.customers")


def test_plan_threshold_blocks_excessive_cost() -> None:
    summary = parse_plan_summary(
        [{"Plan": {"Node Type": "Seq Scan", "Plan Rows": 1, "Total Cost": 10.0}}]
    )

    with pytest.raises(QueryPlanThresholdExceededError):
        enforce_plan_thresholds(
            summary,
            Settings(environment="test", sql_guardrail_max_plan_total_cost=1.0),
        )


def test_execute_validates_before_opening_database_connection() -> None:
    engine = FakeEngine(
        FakeConnection(
            raw_plan=[{"Plan": {"Node Type": "Seq Scan", "Plan Rows": 1, "Total Cost": 1.0}}],
            rows=(),
        )
    )
    service = QueryExecutionService(cast(Engine, engine), Settings(environment="test"))

    with pytest.raises(SQLGuardrailValidationError):
        service.execute("DELETE FROM commerce.orders", fake_catalog())

    assert engine.connect_count == 0


def test_execute_runs_explain_then_query_and_rolls_back() -> None:
    connection = FakeConnection(
        raw_plan=[
            {
                "Plan": {
                    "Node Type": "Seq Scan",
                    "Plan Rows": 2,
                    "Total Cost": 3.5,
                    "Relation Name": "orders",
                    "Schema": "commerce",
                }
            }
        ],
        rows=({"order_id": 1}, {"order_id": 2}),
    )
    engine = FakeEngine(connection)
    service = QueryExecutionService(
        cast(Engine, engine),
        Settings(environment="test", sql_execution_max_rows=1),
    )

    result = service.execute("SELECT order_id FROM commerce.orders", fake_catalog())

    assert result.row_count == 1
    assert result.rows == ({"order_id": 1},)
    assert result.truncated is True
    assert result.columns[0].name == "order_id"
    assert result.plan.referenced_relations == ("commerce.orders",)
    assert connection.driver_sql_calls == (
        "EXPLAIN (FORMAT JSON, COSTS TRUE, VERBOSE TRUE) "
        "SELECT order_id FROM commerce.orders LIMIT 1000",
        "SELECT order_id FROM commerce.orders LIMIT 1000",
    )
    assert connection.transaction.rolled_back is True
    assert connection.transaction.committed is False


def test_expensive_plan_blocks_before_query_execution() -> None:
    connection = FakeConnection(
        raw_plan=[
            {
                "Plan": {
                    "Node Type": "Seq Scan",
                    "Plan Rows": 100,
                    "Total Cost": 100.0,
                    "Relation Name": "orders",
                    "Schema": "commerce",
                }
            }
        ],
        rows=({"order_id": 1},),
    )
    service = QueryExecutionService(
        cast(Engine, FakeEngine(connection)),
        Settings(environment="test", sql_guardrail_max_plan_total_cost=1.0),
    )

    with pytest.raises(QueryPlanThresholdExceededError):
        service.execute("SELECT order_id FROM commerce.orders", fake_catalog())

    assert connection.driver_sql_calls == (
        "EXPLAIN (FORMAT JSON, COSTS TRUE, VERBOSE TRUE) "
        "SELECT order_id FROM commerce.orders LIMIT 1000",
    )
    assert connection.transaction.rolled_back is True


def test_configure_read_only_transaction_sets_local_controls() -> None:
    connection = FakeConnection(
        raw_plan=[{"Plan": {"Node Type": "Result", "Plan Rows": 1, "Total Cost": 1.0}}],
        rows=(),
    )

    configure_read_only_transaction(
        connection,
        Settings(
            environment="test",
            database_statement_timeout_ms=2500,
            sql_execution_lock_timeout_ms=125,
        ),
    )

    assert connection.execute_calls == (
        "SET TRANSACTION READ ONLY",
        "SET LOCAL lock_timeout = 125",
        "SET LOCAL idle_in_transaction_session_timeout = 2500",
    )


@dataclass
class FakeEngine:
    connection: FakeConnection
    connect_count: int = 0

    def connect(self) -> FakeConnectionManager:
        self.connect_count += 1
        return FakeConnectionManager(self.connection)


@dataclass
class FakeConnectionManager:
    connection: FakeConnection

    def __enter__(self) -> FakeConnection:
        return self.connection

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


@dataclass
class FakeTransaction:
    is_active: bool = True
    rolled_back: bool = False
    committed: bool = False

    def rollback(self) -> None:
        self.rolled_back = True
        self.is_active = False

    def commit(self) -> None:
        self.committed = True
        self.is_active = False


@dataclass
class FakeConnection:
    raw_plan: Any
    rows: tuple[dict[str, Any], ...]
    execute_calls: tuple[str, ...] = ()
    driver_sql_calls: tuple[str, ...] = ()
    transaction: FakeTransaction = field(default_factory=FakeTransaction)

    def begin(self) -> FakeTransaction:
        return self.transaction

    def execute(self, statement: object) -> FakeScalarResult:
        self.execute_calls = (*self.execute_calls, str(statement))
        return FakeScalarResult(None)

    def exec_driver_sql(self, sql: str) -> FakeScalarResult | FakeCursorResult:
        self.driver_sql_calls = (*self.driver_sql_calls, sql)
        if sql.startswith("EXPLAIN"):
            return FakeScalarResult(self.raw_plan)
        return FakeCursorResult(self.rows)


@dataclass
class FakeScalarResult:
    value: Any

    def scalar_one(self) -> Any:
        return self.value


@dataclass
class FakeCursorResult:
    rows: tuple[dict[str, Any], ...]
    cursor: FakeCursor = field(default_factory=lambda: FakeCursor((("order_id", 20),)))

    def keys(self) -> tuple[str, ...]:
        if not self.rows:
            return ("order_id",)
        return tuple(self.rows[0])

    def mappings(self) -> FakeCursorResult:
        return self

    def fetchmany(self, size: int) -> list[dict[str, Any]]:
        return list(self.rows[:size])


@dataclass
class FakeCursor:
    description: tuple[tuple[str, int], ...]


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
                        ColumnSchema("status", "TEXT", False),
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
