import pytest

from app.core.config import Settings
from app.db.engine import create_database_engine
from app.services.schema_introspection import SchemaIntrospectionService


@pytest.mark.integration
def test_schema_introspection_represents_seeded_business_tables() -> None:
    engine = create_database_engine(Settings(environment="test"))

    try:
        database_schema = SchemaIntrospectionService(
            engine,
            Settings(environment="test"),
        ).introspect()
    finally:
        engine.dispose()

    assert database_schema.schemas == ("commerce",)
    assert [table.name for table in database_schema.tables] == [
        "categories",
        "customers",
        "order_items",
        "orders",
        "payments",
        "products",
        "refunds",
        "shipments",
    ]

    table_by_name = {table.name: table for table in database_schema.tables}
    assert table_by_name["customers"].primary_key.columns == ("customer_id",)
    assert [column.name for column in table_by_name["orders"].columns] == [
        "order_id",
        "customer_id",
        "order_number",
        "ordered_at",
        "status",
        "billing_region",
        "currency",
        "subtotal_cents",
        "discount_cents",
        "tax_cents",
        "shipping_cents",
        "total_cents",
    ]

    foreign_key_paths = {
        foreign_key.display_path
        for table in database_schema.tables
        for foreign_key in table.foreign_keys
    }

    assert foreign_key_paths == {
        "commerce.categories.parent_category_id -> commerce.categories.category_id",
        "commerce.order_items.order_id -> commerce.orders.order_id",
        "commerce.order_items.product_id -> commerce.products.product_id",
        "commerce.orders.customer_id -> commerce.customers.customer_id",
        "commerce.payments.order_id -> commerce.orders.order_id",
        "commerce.products.category_id -> commerce.categories.category_id",
        "commerce.refunds.payment_id -> commerce.payments.payment_id",
        "commerce.shipments.order_id -> commerce.orders.order_id",
    }
