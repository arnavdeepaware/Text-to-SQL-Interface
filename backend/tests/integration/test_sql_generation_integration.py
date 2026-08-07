import pytest

from app.core.config import Settings
from app.db.engine import create_database_engine
from app.domain.schema_catalog import SchemaCatalog
from app.domain.sql_generation import SQLGenerationResult
from app.providers.fake_sql_generation import FakeSQLGenerator
from app.services.glossary_loader import BusinessGlossaryLoader
from app.services.prompt_engine import SchemaAwarePromptEngine
from app.services.schema_introspection import SchemaIntrospectionService
from app.services.schema_retrieval import LexicalSchemaRetriever
from app.services.schema_sampling import SchemaSampleService


@pytest.mark.integration
def test_fake_sql_generation_with_seeded_schema_prompt_does_not_execute_sql() -> None:
    settings = Settings(environment="test")
    engine = create_database_engine(settings)

    try:
        database_schema = SchemaIntrospectionService(engine, settings).introspect()
        samples = SchemaSampleService(engine, settings).collect_samples(database_schema)
    finally:
        engine.dispose()

    catalog = SchemaCatalog(
        database_schema=database_schema,
        samples=samples,
        glossary=BusinessGlossaryLoader().load(),
        generated_at_epoch_seconds=100.0,
        cache_expires_at_epoch_seconds=400.0,
        refreshed=False,
    )
    question = "Calculate net revenue"
    retrieval = LexicalSchemaRetriever(settings).retrieve(
        question,
        catalog.database_schema,
        catalog.glossary,
    )
    prompt = SchemaAwarePromptEngine(settings).build_prompt(question, catalog, retrieval)
    result = SQLGenerationResult(
        sql="SELECT sum(orders.total_cents) FROM commerce.orders AS orders;",
        explanation="Draft only; not executed.",
        model_confidence=0.8,
        tables_used=["commerce.orders"],
        columns_used=["commerce.orders.total_cents"],
        assumptions=[],
        clarification_needed=False,
        clarification_options=[],
    )

    draft = FakeSQLGenerator(result=result).generate(prompt)

    assert draft.result.sql == "SELECT sum(orders.total_cents) FROM commerce.orders AS orders;"
    assert draft.telemetry.provider_name == "fake"
