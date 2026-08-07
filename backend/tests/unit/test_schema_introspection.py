from typing import Any
from unittest.mock import Mock

from sqlalchemy import Engine

from app.core.config import Settings
from app.services.schema_introspection import (
    SchemaInspector,
    SchemaIntrospectionService,
    is_postgresql_internal_schema,
    is_project_audit_table,
)


class MockInspector:
    def get_schema_names(self) -> list[str]:
        return ["pg_catalog", "commerce", "information_schema", "scratch"]

    def get_table_names(self, schema: str | None = None) -> list[str]:
        assert schema == "commerce"
        return ["orders", "audit_log", "customers", "orders_audit"]

    def get_columns(self, table_name: str, schema: str | None = None) -> list[dict[str, Any]]:
        assert schema == "commerce"
        columns_by_table = {
            "customers": [
                {
                    "name": "customer_id",
                    "type": "BIGINT",
                    "nullable": False,
                    "default": "identity",
                },
                {"name": "email", "type": "TEXT", "nullable": False, "default": None},
            ],
            "orders": [
                {"name": "order_id", "type": "BIGINT", "nullable": False, "default": None},
                {"name": "customer_id", "type": "BIGINT", "nullable": False, "default": None},
                {"name": "status", "type": "TEXT", "nullable": False, "default": "'pending'"},
            ],
        }
        return columns_by_table[table_name]

    def get_pk_constraint(
        self,
        table_name: str,
        schema: str | None = None,
    ) -> dict[str, Any]:
        assert schema == "commerce"
        primary_keys = {
            "customers": {
                "constrained_columns": ["customer_id"],
                "name": "customers_pkey",
            },
            "orders": {
                "constrained_columns": ["order_id"],
                "name": "orders_pkey",
            },
        }
        return primary_keys[table_name]

    def get_foreign_keys(
        self,
        table_name: str,
        schema: str | None = None,
    ) -> list[dict[str, Any]]:
        assert schema == "commerce"
        if table_name == "orders":
            return [
                {
                    "name": "orders_customer_id_fkey",
                    "constrained_columns": ["customer_id"],
                    "referred_schema": "commerce",
                    "referred_table": "customers",
                    "referred_columns": ["customer_id"],
                    "options": {"ondelete": "RESTRICT"},
                }
            ]
        return []


def test_schema_introspection_builds_typed_schema_with_deterministic_order() -> None:
    service = SchemaIntrospectionService(
        Mock(spec=Engine),
        Settings(environment="test"),
        inspector=MockInspector(),
    )

    database_schema = service.introspect()

    assert database_schema.schemas == ("commerce",)
    assert [table.identifier for table in database_schema.tables] == [
        "commerce.customers",
        "commerce.orders",
    ]

    customers = database_schema.table("commerce", "customers")
    assert customers is not None
    assert [column.name for column in customers.columns] == ["customer_id", "email"]
    assert customers.columns[0].sql_type == "BIGINT"
    assert customers.columns[0].nullable is False
    assert customers.columns[0].default == "identity"
    assert customers.primary_key.columns == ("customer_id",)
    assert customers.primary_key.name == "customers_pkey"

    orders = database_schema.table("commerce", "orders")
    assert orders is not None
    assert orders.primary_key.columns == ("order_id",)
    assert len(orders.foreign_keys) == 1
    foreign_key = orders.foreign_keys[0]
    assert foreign_key.constrained_columns == ("customer_id",)
    assert foreign_key.referred_schema == "commerce"
    assert foreign_key.referred_table == "customers"
    assert foreign_key.referred_columns == ("customer_id",)
    assert (
        foreign_key.display_path
        == "commerce.orders.customer_id -> commerce.customers.customer_id"
    )


def test_foreign_keys_are_sorted_stably() -> None:
    inspector = Mock(spec=SchemaInspector)
    inspector.get_schema_names.return_value = ["commerce"]
    inspector.get_table_names.return_value = ["order_items"]
    inspector.get_columns.return_value = []
    inspector.get_pk_constraint.return_value = {
        "constrained_columns": ["order_item_id"],
        "name": "order_items_pkey",
    }
    inspector.get_foreign_keys.return_value = [
        {
            "name": "order_items_product_id_fkey",
            "constrained_columns": ["product_id"],
            "referred_schema": "commerce",
            "referred_table": "products",
            "referred_columns": ["product_id"],
        },
        {
            "name": "order_items_order_id_fkey",
            "constrained_columns": ["order_id"],
            "referred_schema": "commerce",
            "referred_table": "orders",
            "referred_columns": ["order_id"],
        },
    ]

    service = SchemaIntrospectionService(
        Mock(spec=Engine),
        Settings(environment="test"),
        inspector=inspector,
    )

    table = service.introspect().table("commerce", "order_items")

    assert table is not None
    assert [foreign_key.constrained_columns for foreign_key in table.foreign_keys] == [
        ("order_id",),
        ("product_id",),
    ]


def test_internal_schema_and_audit_table_predicates() -> None:
    assert is_postgresql_internal_schema("pg_catalog")
    assert is_postgresql_internal_schema("pg_toast")
    assert is_postgresql_internal_schema("information_schema")
    assert not is_postgresql_internal_schema("commerce")

    assert is_project_audit_table("audit_log")
    assert is_project_audit_table("audit_orders")
    assert is_project_audit_table("orders_audit")
    assert is_project_audit_table("orders_audit_logs")
    assert not is_project_audit_table("orders")
