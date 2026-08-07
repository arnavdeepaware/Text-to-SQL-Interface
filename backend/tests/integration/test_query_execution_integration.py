import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.db.engine import create_database_engine
from app.domain.sql_generation import SQLGenerationResult
from app.main import create_app
from app.providers.fake_sql_generation import FakeSQLGenerator
from app.services.glossary_loader import BusinessGlossaryLoader
from app.services.query_execution import QueryExecutionService
from app.services.schema_catalog import SchemaCatalogService
from app.services.sql_guardrails import SQLGuardrailValidationError


@pytest.mark.integration
async def test_query_endpoint_executes_safe_approved_sql_against_postgres() -> None:
    result = SQLGenerationResult(
        sql=(
            "SELECT orders.order_id, orders.status "
            "FROM commerce.orders AS orders "
            "ORDER BY orders.order_id "
            "LIMIT 2;"
        ),
        explanation="Returns two orders.",
        model_confidence=0.91,
        tables_used=["commerce.orders"],
        columns_used=["commerce.orders.order_id", "commerce.orders.status"],
        assumptions=[],
        clarification_needed=False,
        clarification_options=[],
    )
    app = create_app(
        settings=Settings(environment="test"),
        sql_generator_factory=lambda settings: FakeSQLGenerator(result=result),
    )

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/v1/query",
                json={"question": "Show all orders with status"},
                headers={"X-Request-ID": "req-run-integration"},
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["result_type"] == "query_result"
    assert payload["request_id"] == "req-run-integration"
    assert payload["columns"][0]["name"] == "order_id"
    assert payload["columns"][1]["name"] == "status"
    assert payload["row_count"] == 2
    assert payload["truncated"] is False
    assert payload["rows"] == [
        {"order_id": 1, "status": "delivered"},
        {"order_id": 2, "status": "delivered"},
    ]
    assert payload["plan"]["estimated_rows"] >= 0
    assert payload["plan"]["total_cost"] > 0
    assert payload["plan"]["plan_nodes"]
    assert payload["guardrails"]["statement_type"] == "select"
    assert payload["guardrails"]["effective_limit"] == 2
    assert payload["guardrails"]["findings"] == []
    assert payload["hallucination_confidence"] == {
        "status": "not_evaluated",
        "score": None,
    }
    assert "raw_plan" not in payload


@pytest.mark.integration
async def test_query_endpoint_blocks_expensive_plan_before_execution() -> None:
    result = SQLGenerationResult(
        sql="SELECT orders.order_id FROM commerce.orders AS orders;",
        explanation="Would exceed the intentionally tiny plan threshold.",
        model_confidence=0.7,
        tables_used=["commerce.orders"],
        columns_used=["commerce.orders.order_id"],
        assumptions=[],
        clarification_needed=False,
        clarification_options=[],
    )
    app = create_app(
        settings=Settings(
            environment="test",
            sql_guardrail_max_plan_total_cost=0.0,
        ),
        sql_generator_factory=lambda settings: FakeSQLGenerator(result=result),
    )

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/v1/query",
                json={"question": "Show all orders"},
                headers={"X-Request-ID": "req-plan-block"},
            )

    assert response.status_code == 422
    assert response.json()["error"] == {
        "code": "sql_guardrail_plan_too_expensive",
        "message": "Generated SQL exceeded planning safety limits.",
        "request_id": "req-plan-block",
    }


@pytest.mark.integration
async def test_query_endpoint_executes_multi_table_aggregation_against_postgres() -> None:
    result = SQLGenerationResult(
        sql=(
            "SELECT customers.region, count(orders.order_id) AS order_count "
            "FROM commerce.customers AS customers "
            "JOIN commerce.orders AS orders "
            "ON orders.customer_id = customers.customer_id "
            "GROUP BY customers.region "
            "ORDER BY customers.region;"
        ),
        explanation="Counts orders by customer region.",
        model_confidence=0.88,
        tables_used=["commerce.customers", "commerce.orders"],
        columns_used=[
            "commerce.customers.region",
            "commerce.customers.customer_id",
            "commerce.orders.order_id",
            "commerce.orders.customer_id",
        ],
        assumptions=[],
        clarification_needed=False,
        clarification_options=[],
    )
    app = create_app(
        settings=Settings(environment="test"),
        sql_generator_factory=lambda settings: FakeSQLGenerator(result=result),
    )

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/v1/query",
                json={"question": "Show all orders by customer region"},
                headers={"X-Request-ID": "req-aggregation"},
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["rows"] == [
        {"region": "International", "order_count": 2},
        {"region": "Midwest", "order_count": 1},
        {"region": "Northeast", "order_count": 2},
        {"region": "South", "order_count": 1},
        {"region": "West", "order_count": 3},
    ]


@pytest.mark.integration
async def test_query_endpoint_executes_bridge_table_query_against_postgres() -> None:
    result = SQLGenerationResult(
        sql=(
            "SELECT DISTINCT customers.customer_id, customers.full_name "
            "FROM commerce.customers AS customers "
            "JOIN commerce.orders AS orders "
            "ON orders.customer_id = customers.customer_id "
            "JOIN commerce.order_items AS order_items "
            "ON order_items.order_id = orders.order_id "
            "JOIN commerce.products AS products "
            "ON products.product_id = order_items.product_id "
            "JOIN commerce.categories AS categories "
            "ON categories.category_id = products.category_id "
            "WHERE categories.name = 'Electronics' "
            "ORDER BY customers.customer_id;"
        ),
        explanation="Finds customers through orders and order_items bridge tables.",
        model_confidence=0.84,
        tables_used=[
            "commerce.customers",
            "commerce.orders",
            "commerce.order_items",
            "commerce.products",
            "commerce.categories",
        ],
        columns_used=[
            "commerce.customers.customer_id",
            "commerce.customers.full_name",
            "commerce.orders.customer_id",
            "commerce.order_items.order_id",
            "commerce.order_items.product_id",
            "commerce.products.product_id",
            "commerce.products.category_id",
            "commerce.categories.category_id",
            "commerce.categories.name",
        ],
        assumptions=[],
        clarification_needed=False,
        clarification_options=[],
    )
    app = create_app(
        settings=Settings(environment="test"),
        sql_generator_factory=lambda settings: FakeSQLGenerator(result=result),
    )

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/v1/query",
                json={"question": "Which customers bought electronics?"},
                headers={"X-Request-ID": "req-bridge"},
            )

    assert response.status_code == 200
    assert response.json()["rows"] == [
        {"customer_id": 2, "full_name": "Bob Martinez"},
        {"customer_id": 5, "full_name": "Eva Rossi"},
    ]


@pytest.mark.integration
async def test_query_endpoint_maps_database_statement_timeout() -> None:
    result = SQLGenerationResult(
        sql="SELECT pg_sleep(1) AS slept;",
        explanation="Intentionally slow query for timeout testing.",
        model_confidence=0.5,
        tables_used=[],
        columns_used=[],
        assumptions=[],
        clarification_needed=False,
        clarification_options=[],
    )
    app = create_app(
        settings=Settings(environment="test", database_statement_timeout_ms=100),
        sql_generator_factory=lambda settings: FakeSQLGenerator(result=result),
    )

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/v1/query",
                json={"question": "Show all orders slowly"},
                headers={"X-Request-ID": "req-exec-timeout"},
            )

    assert response.status_code == 504
    assert response.json()["error"] == {
        "code": "sql_execution_timeout",
        "message": "Generated SQL execution timed out.",
        "request_id": "req-exec-timeout",
    }


@pytest.mark.integration
def test_query_execution_service_blocks_write_attempt_before_database() -> None:
    settings = Settings(environment="test")
    engine = create_database_engine(settings)
    try:
        catalog = SchemaCatalogService(
            engine,
            settings,
            glossary_loader=BusinessGlossaryLoader(),
        ).get_schema(refresh=True)
        service = QueryExecutionService(engine, settings)

        with pytest.raises(SQLGuardrailValidationError):
            service.execute("INSERT INTO commerce.categories (name) VALUES ('Unsafe')", catalog)
    finally:
        engine.dispose()


@pytest.mark.integration
def test_application_database_role_cannot_write_directly() -> None:
    settings = Settings(environment="test")
    engine = create_database_engine(settings)
    try:
        with engine.connect() as connection:
            assert connection.execute(text("SELECT current_user")).scalar_one() == (
                settings.database_user
            )
            default_read_only = connection.execute(
                text("SHOW default_transaction_read_only")
            ).scalar_one()
            assert default_read_only == "on"

        denied_statements = (
            "INSERT INTO commerce.categories (name) VALUES ('Forbidden')",
            "UPDATE commerce.orders SET status = 'paid' WHERE order_id = 1",
            "DELETE FROM commerce.orders WHERE order_id = 1",
            "CREATE TABLE commerce.forbidden_write (id integer)",
            "CREATE TEMP TABLE forbidden_temp (id integer)",
        )
        for statement in denied_statements:
            with engine.connect() as connection:
                with pytest.raises(SQLAlchemyError):
                    connection.execute(text(statement))
                connection.rollback()
    finally:
        engine.dispose()


@pytest.mark.integration
def test_query_execution_transaction_is_read_only() -> None:
    settings = Settings(environment="test")
    engine = create_database_engine(settings)
    try:
        catalog = SchemaCatalogService(
            engine,
            settings,
            glossary_loader=BusinessGlossaryLoader(),
        ).get_schema(refresh=True)
        result = QueryExecutionService(engine, settings).execute(
            "SELECT current_setting('transaction_read_only') AS tx_read_only",
            catalog,
        )
    finally:
        engine.dispose()

    assert result.rows == ({"tx_read_only": "on"},)
