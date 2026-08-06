from typing import cast
from unittest.mock import Mock

from httpx import ASGITransport, AsyncClient
from sqlalchemy import Engine

from app.core.config import Settings
from app.domain.glossary import BusinessGlossary, GlossaryTerm
from app.domain.schema import (
    ColumnSchema,
    DatabaseSchema,
    ForeignKeySchema,
    PrimaryKeySchema,
    TableSchema,
)
from app.domain.schema_catalog import ColumnSample, SchemaCatalog
from app.main import create_app


class FakeSchemaCatalogService:
    def __init__(self) -> None:
        self.refresh_values: list[bool] = []

    def get_schema(self, refresh: bool = False) -> SchemaCatalog:
        self.refresh_values.append(refresh)
        return fake_catalog(refreshed=refresh)


async def test_schema_endpoint_returns_schema_and_passes_refresh_flag() -> None:
    fake_engine = Mock(spec=Engine)
    fake_service = FakeSchemaCatalogService()
    app = create_app(
        settings=Settings(environment="test"),
        engine_factory=lambda settings: cast(Engine, fake_engine),
        schema_catalog_factory=lambda engine, settings: fake_service,
    )
    transport = ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/v1/schema")
            refresh_response = await client.get("/v1/schema?refresh=true")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schemas"] == ["commerce"]
    assert payload["tables"][0]["identifier"] == "commerce.orders"
    assert payload["tables"][0]["columns"][0]["sample_values"] == ["paid", "pending"]
    assert payload["relationships"][0]["display_path"] == (
        "commerce.orders.customer_id -> commerce.customers.customer_id"
    )
    assert payload["glossary"]["terms"][0]["name"] == "gross revenue"
    assert payload["cache"]["refreshed"] is False

    assert refresh_response.status_code == 200
    assert refresh_response.json()["cache"]["refreshed"] is True
    assert fake_service.refresh_values == [False, True]


def fake_catalog(refreshed: bool) -> SchemaCatalog:
    orders = TableSchema(
        schema_name="commerce",
        name="orders",
        columns=(
            ColumnSchema("status", "TEXT", False),
            ColumnSchema("customer_id", "BIGINT", False),
        ),
        primary_key=PrimaryKeySchema(("order_id",), "orders_pkey"),
        foreign_keys=(
            ForeignKeySchema(
                source_schema="commerce",
                source_table="orders",
                constrained_columns=("customer_id",),
                referred_schema="commerce",
                referred_table="customers",
                referred_columns=("customer_id",),
                name="orders_customer_id_fkey",
            ),
        ),
    )
    return SchemaCatalog(
        database_schema=DatabaseSchema(schemas=("commerce",), tables=(orders,)),
        samples=(
            ColumnSample(
                table_identifier="commerce.orders",
                column_name="status",
                values=("paid", "pending"),
            ),
        ),
        glossary=BusinessGlossary(
            version=1,
            terms=(
                GlossaryTerm(
                    name="gross revenue",
                    definition="Total order value.",
                    expression="sum(orders.total_cents)",
                    related_tables=("orders",),
                    related_columns=("orders.total_cents",),
                ),
            ),
        ),
        generated_at_epoch_seconds=100.0,
        cache_expires_at_epoch_seconds=400.0,
        refreshed=refreshed,
    )

