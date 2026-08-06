import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app


@pytest.mark.integration
async def test_schema_endpoint_returns_safe_enriched_seeded_schema() -> None:
    app = create_app(settings=Settings(environment="test"))

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/v1/schema")
            refresh_response = await client.get("/v1/schema?refresh=true")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schemas"] == ["commerce"]
    assert [table["name"] for table in payload["tables"]] == [
        "categories",
        "customers",
        "order_items",
        "orders",
        "payments",
        "products",
        "refunds",
        "shipments",
    ]

    columns_by_table = {
        table["name"]: {
            column["name"]: column
            for column in table["columns"]
        }
        for table in payload["tables"]
    }

    assert columns_by_table["orders"]["status"]["sample_values"] == [
        "cancelled",
        "delivered",
        "pending",
        "shipped",
    ]
    assert columns_by_table["customers"]["region"]["sample_values"] == [
        "International",
        "Midwest",
        "Northeast",
        "South",
        "West",
    ]
    assert columns_by_table["customers"]["email"]["sample_values"] == []
    assert columns_by_table["customers"]["full_name"]["sample_values"] == []
    assert columns_by_table["payments"]["provider_payment_id"]["sample_values"] == []
    assert columns_by_table["shipments"]["tracking_number"]["sample_values"] == []

    assert {
        relationship["display_path"]
        for relationship in payload["relationships"]
    } >= {
        "commerce.orders.customer_id -> commerce.customers.customer_id",
        "commerce.refunds.payment_id -> commerce.payments.payment_id",
    }
    assert {term["name"] for term in payload["glossary"]["terms"]} >= {
        "gross revenue",
        "net revenue",
        "completed order",
        "refunded order",
        "delivery time",
    }
    assert payload["cache"]["refreshed"] is False
    assert refresh_response.status_code == 200
    assert refresh_response.json()["cache"]["refreshed"] is True
