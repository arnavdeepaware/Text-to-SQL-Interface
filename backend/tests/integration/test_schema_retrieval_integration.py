import pytest

from app.core.config import Settings
from app.db.engine import create_database_engine
from app.services.glossary_loader import BusinessGlossaryLoader
from app.services.schema_introspection import SchemaIntrospectionService
from app.services.schema_retrieval import LexicalSchemaRetriever


@pytest.mark.integration
def test_schema_retrieval_uses_seeded_schema_relationships() -> None:
    settings = Settings(environment="test")
    engine = create_database_engine(settings)

    try:
        database_schema = SchemaIntrospectionService(engine, settings).introspect()
    finally:
        engine.dispose()

    glossary = BusinessGlossaryLoader().load()
    result = LexicalSchemaRetriever(
        settings.model_copy(update={"schema_retrieval_min_table_score": 10.0})
    ).retrieve("Gross revenue by product category", database_schema, glossary)

    selected_table_names = {table.table_name for table in result.selected_tables}
    relationship_steps = {
        step.display_path
        for path in result.relationship_paths
        for step in path.steps
    }

    assert {"orders", "order_items", "products", "categories"} <= selected_table_names
    assert "commerce.order_items.order_id -> commerce.orders.order_id" in relationship_steps
    assert "commerce.order_items.product_id -> commerce.products.product_id" in relationship_steps
    assert "commerce.products.category_id -> commerce.categories.category_id" in relationship_steps
