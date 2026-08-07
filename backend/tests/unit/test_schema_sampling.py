from typing import cast
from unittest.mock import MagicMock, Mock

from sqlalchemy import Engine
from sqlalchemy.dialects import postgresql

from app.core.config import Settings
from app.domain.schema import ColumnSchema, DatabaseSchema, PrimaryKeySchema, TableSchema
from app.services.schema_sampling import (
    SchemaSampleService,
    is_sensitive_column_name,
    is_textual_sql_type,
)


def test_schema_sampling_collects_only_configured_non_sensitive_text_columns() -> None:
    engine = Mock(spec=Engine)
    engine.dialect = postgresql.dialect()
    connection = Mock()
    sample_result = Mock()
    sample_result.scalars.return_value.all.return_value = ["paid", "pending"]
    connection.execute.side_effect = [Mock(), sample_result]
    connection_manager = MagicMock()
    connection_manager.__enter__.return_value = connection
    engine.connect.return_value = connection_manager

    database_schema = DatabaseSchema(
        schemas=("commerce",),
        tables=(
            TableSchema(
                schema_name="commerce",
                name="orders",
                columns=(
                    ColumnSchema("status", "TEXT", False),
                    ColumnSchema("order_number", "TEXT", False),
                    ColumnSchema("total_cents", "INTEGER", False),
                ),
                primary_key=PrimaryKeySchema(("order_id",), "orders_pkey"),
            ),
        ),
    )
    service = SchemaSampleService(
        cast(Engine, engine),
        Settings(
            environment="test",
            schema_sample_columns=(
                "commerce.orders.status",
                "commerce.orders.order_number",
                "commerce.orders.total_cents",
            ),
            schema_sample_limit=5,
            schema_sample_timeout_ms=250,
        ),
    )

    samples = service.collect_samples(database_schema)

    assert [(sample.column_name, sample.values) for sample in samples] == [
        ("status", ("paid", "pending"))
    ]
    assert connection.execute.call_count == 2
    timeout_call = connection.execute.call_args_list[0]
    assert "SET LOCAL statement_timeout = 250" in str(timeout_call.args[0])


def test_schema_sampling_skips_high_cardinality_results() -> None:
    engine = Mock(spec=Engine)
    engine.dialect = postgresql.dialect()
    connection = Mock()
    sample_result = Mock()
    sample_result.scalars.return_value.all.return_value = ["a", "b", "c"]
    connection.execute.side_effect = [Mock(), sample_result]
    connection_manager = MagicMock()
    connection_manager.__enter__.return_value = connection
    engine.connect.return_value = connection_manager

    database_schema = DatabaseSchema(
        schemas=("commerce",),
        tables=(
            TableSchema(
                schema_name="commerce",
                name="orders",
                columns=(ColumnSchema("status", "TEXT", False),),
                primary_key=PrimaryKeySchema(("order_id",), "orders_pkey"),
            ),
        ),
    )

    samples = SchemaSampleService(
        cast(Engine, engine),
        Settings(
            environment="test",
            schema_sample_columns=("commerce.orders.status",),
            schema_sample_limit=2,
        ),
    ).collect_samples(database_schema)

    assert samples == ()


def test_schema_sampling_safety_predicates() -> None:
    assert is_textual_sql_type("VARCHAR(10)")
    assert is_textual_sql_type("CHAR(2)")
    assert is_textual_sql_type("TEXT")
    assert not is_textual_sql_type("INTEGER")

    assert is_sensitive_column_name("email")
    assert is_sensitive_column_name("provider_payment_id")
    assert is_sensitive_column_name("tracking_number")
    assert not is_sensitive_column_name("billing_region")
