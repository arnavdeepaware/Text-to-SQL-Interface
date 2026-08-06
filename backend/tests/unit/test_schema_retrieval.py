from app.core.config import Settings
from app.domain.glossary import BusinessGlossary, GlossaryTerm
from app.domain.schema import (
    ColumnSchema,
    DatabaseSchema,
    ForeignKeySchema,
    PrimaryKeySchema,
    TableSchema,
)
from app.domain.schema_retrieval import SchemaRetrievalResult
from app.providers.embeddings import EmbeddingProviderError, OpenAIEmbeddingProvider
from app.services.schema_retrieval import EmbeddingSchemaRetriever, LexicalSchemaRetriever


def test_sales_synonym_selects_revenue_context() -> None:
    result = retrieve("Show sales by month")

    assert selected_table_names(result)[0] == "orders"
    assert "commerce.orders.total_cents" in selected_column_ids(result)
    assert "refunds" not in selected_table_names(result)


def test_revenue_question_selects_orders_and_revenue_columns() -> None:
    result = retrieve("Show gross revenue by month")

    assert selected_table_names(result)[:1] == ["orders"]
    assert "commerce.orders.total_cents" in selected_column_ids(result)
    assert "gross revenue" in result.glossary_terms
    assert result.strategy == "lexical"


def test_refund_question_preserves_refunds_payments_orders_path() -> None:
    result = retrieve("How much net revenue was refunded?")

    assert {"orders", "payments", "refunds"} <= set(selected_table_names(result))
    assert "commerce.refunds.amount_cents" in selected_column_ids(result)
    assert (
        "commerce.refunds.payment_id -> commerce.payments.payment_id"
        in relationship_steps(result)
    )
    assert "commerce.payments.order_id -> commerce.orders.order_id" in relationship_steps(result)


def test_net_revenue_requires_refunds_context() -> None:
    result = retrieve("Calculate net revenue")

    assert {"orders", "payments", "refunds"} <= set(selected_table_names(result))
    assert "order_items" not in selected_table_names(result)
    assert "commerce.orders.total_cents" in selected_column_ids(result)
    assert "commerce.refunds.amount_cents" in selected_column_ids(result)
    assert "net revenue" in result.glossary_terms


def test_customer_region_question_selects_customer_order_relationship() -> None:
    result = retrieve("Revenue by customer region")

    assert {"customers", "orders"} <= set(selected_table_names(result))
    assert "commerce.customers.region" in selected_column_ids(result)
    assert (
        "commerce.orders.customer_id -> commerce.customers.customer_id"
        in relationship_steps(result)
    )


def test_customer_category_question_includes_order_bridges() -> None:
    result = retrieve("Customers by category", min_table_score=25.0)

    assert {"customers", "orders", "order_items", "products", "categories"} <= set(
        selected_table_names(result)
    )
    bridge_tables = {table.table_name for table in result.selected_tables if table.bridge}
    assert {"orders", "order_items"} <= bridge_tables
    assert "commerce.orders.customer_id -> commerce.customers.customer_id" in relationship_steps(
        result
    )
    assert "commerce.order_items.order_id -> commerce.orders.order_id" in relationship_steps(
        result
    )
    assert (
        "commerce.order_items.product_id -> commerce.products.product_id"
        in relationship_steps(result)
    )


def test_delivery_time_question_selects_shipments_and_time_columns() -> None:
    result = retrieve("Average delivery time by carrier")

    assert selected_table_names(result)[0] == "shipments"
    assert {
        "commerce.shipments.shipped_at",
        "commerce.shipments.delivered_at",
        "commerce.shipments.carrier",
    } <= selected_column_ids(result)
    assert "delivery time" in result.glossary_terms


def test_product_category_question_selects_direct_relationship() -> None:
    result = retrieve("Active products by category")

    assert {"products", "categories"} <= set(selected_table_names(result))
    assert (
        "commerce.products.category_id -> commerce.categories.category_id"
        in relationship_steps(result)
    )


def test_bridge_tables_are_included_for_revenue_by_category() -> None:
    result = retrieve("Gross revenue by category", min_table_score=10.0)

    assert {"orders", "order_items", "products", "categories"} <= set(selected_table_names(result))
    bridge_tables = {table.table_name for table in result.selected_tables if table.bridge}
    assert "order_items" in bridge_tables
    assert "commerce.order_items.order_id -> commerce.orders.order_id" in relationship_steps(result)
    assert (
        "commerce.order_items.product_id -> commerce.products.product_id"
        in relationship_steps(result)
    )


def test_unrelated_question_selects_no_schema_context() -> None:
    result = retrieve("What is the weather forecast for tomorrow?")

    assert result.selected_tables == ()
    assert result.selected_columns == ()
    assert result.relationship_paths == ()
    assert result.glossary_terms == ()


def test_empty_question_selects_no_schema_context() -> None:
    result = retrieve("")

    assert result.selected_tables == ()
    assert result.selected_columns == ()
    assert result.relationship_paths == ()
    assert result.glossary_terms == ()


def test_very_long_input_remains_deterministic_and_relevant() -> None:
    question = " ".join("unrelated" for _ in range(2_000)) + " gross sales by customer region"

    first = retrieve(question)
    second = retrieve(question)

    assert first == second
    assert {"customers", "orders"} <= set(selected_table_names(first))
    assert "commerce.orders.total_cents" in selected_column_ids(first)


def test_missing_glossary_entries_degrades_to_lexical_matching() -> None:
    result = LexicalSchemaRetriever(Settings(environment="test")).retrieve(
        "Refund amount by reason",
        fake_database_schema(),
        BusinessGlossary(version=1, terms=()),
    )

    assert selected_table_names(result)[0] == "refunds"
    assert "commerce.refunds.amount_cents" in selected_column_ids(result)
    assert "commerce.refunds.reason" in selected_column_ids(result)
    assert result.glossary_terms == ()


def test_retrieval_is_deterministic_for_ranking_ties() -> None:
    first = retrieve("status").ranked_columns
    second = retrieve("status").ranked_columns

    assert first == second
    score_groups = {
        column.score: [
            grouped_column.identifier
            for grouped_column in first
            if grouped_column.score == column.score
        ]
        for column in first
    }
    for identifiers in score_groups.values():
        assert identifiers == sorted(identifiers)


def test_table_ranking_ties_are_identifier_sorted() -> None:
    result = retrieve("status")
    score_groups = {
        table.score: [
            grouped_table.identifier
            for grouped_table in result.ranked_tables
            if grouped_table.score == table.score
        ]
        for table in result.ranked_tables
    }

    for identifiers in score_groups.values():
        assert identifiers == sorted(identifiers)


def test_embedding_retriever_degrades_cleanly_without_api_key() -> None:
    provider = OpenAIEmbeddingProvider(Settings(environment="test", openai_api_key=None))
    result = LexicalSchemaRetriever(
        Settings(environment="test", schema_retrieval_use_embeddings=True),
        embedding_provider=provider,
    ).retrieve("Show gross revenue", fake_database_schema(), fake_glossary())

    assert result.strategy == "embedding_fallback"
    assert result.fallback_reason == "embedding provider is not configured"
    assert selected_table_names(result)[0] == "orders"


def test_embedding_retriever_falls_back_when_provider_fails() -> None:
    result = LexicalSchemaRetriever(
        Settings(environment="test", schema_retrieval_use_embeddings=True),
        embedding_provider=FailingEmbeddingProvider(),
    ).retrieve("Show refund revenue", fake_database_schema(), fake_glossary())

    assert result.strategy == "embedding_fallback"
    assert result.fallback_reason == "provider unavailable"
    assert {"orders", "refunds"} <= set(selected_table_names(result))


def test_embedding_retriever_falls_back_when_provider_raises_unexpected_error() -> None:
    result = LexicalSchemaRetriever(
        Settings(environment="test", schema_retrieval_use_embeddings=True),
        embedding_provider=UnexpectedFailingEmbeddingProvider(),
    ).retrieve("Show refund revenue", fake_database_schema(), fake_glossary())

    assert result.strategy == "embedding_fallback"
    assert result.fallback_reason == "embedding provider failed"
    assert {"orders", "refunds"} <= set(selected_table_names(result))


def test_embedding_retriever_falls_back_for_malformed_vectors() -> None:
    result = LexicalSchemaRetriever(
        Settings(environment="test", schema_retrieval_use_embeddings=True),
        embedding_provider=MalformedEmbeddingProvider(),
    ).retrieve("Show refund revenue", fake_database_schema(), fake_glossary())

    assert result.strategy == "embedding_fallback"
    assert result.fallback_reason == "embedding vectors have incompatible dimensions"
    assert {"orders", "refunds"} <= set(selected_table_names(result))


def test_embedding_retriever_can_add_provider_scores() -> None:
    result = EmbeddingSchemaRetriever(
        Settings(environment="test"),
        DeterministicEmbeddingProvider(),
    ).retrieve("Show delivery time", fake_database_schema(), fake_glossary())

    assert result.strategy == "embedding"
    assert result.fallback_reason is None
    assert any(reason.source == "embedding" for reason in result.ranked_tables[0].reasons)


def retrieve(question: str, min_table_score: float = 8.0) -> SchemaRetrievalResult:
    return LexicalSchemaRetriever(
        Settings(environment="test", schema_retrieval_min_table_score=min_table_score)
    ).retrieve(
        question,
        fake_database_schema(),
        fake_glossary(),
    )


def selected_table_names(result: SchemaRetrievalResult) -> list[str]:
    return [table.table_name for table in result.selected_tables]


def selected_column_ids(result: SchemaRetrievalResult) -> set[str]:
    return {column.identifier for column in result.selected_columns}


def relationship_steps(result: SchemaRetrievalResult) -> set[str]:
    return {
        step.display_path
        for path in result.relationship_paths
        for step in path.steps
    }


class FailingEmbeddingProvider:
    @property
    def is_configured(self) -> bool:
        return True

    def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        raise EmbeddingProviderError("provider unavailable")


class UnexpectedFailingEmbeddingProvider:
    @property
    def is_configured(self) -> bool:
        return True

    def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        raise RuntimeError("boom")


class DeterministicEmbeddingProvider:
    @property
    def is_configured(self) -> bool:
        return True

    def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        return tuple((1.0, 0.0) if "delivery" in text else (0.0, 1.0) for text in texts)


class MalformedEmbeddingProvider:
    @property
    def is_configured(self) -> bool:
        return True

    def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        return ((1.0, 0.0), *((1.0,) for _ in texts[1:]))


def fake_glossary() -> BusinessGlossary:
    return BusinessGlossary(
        version=1,
        terms=(
            GlossaryTerm(
                "completed order",
                "An order with status delivered.",
                "orders.status = 'delivered'",
                related_tables=("orders",),
                related_columns=("orders.status",),
            ),
            GlossaryTerm(
                "delivery time",
                "Time elapsed between shipment shipped_at and delivered_at timestamps.",
                "shipments.delivered_at - shipments.shipped_at",
                related_tables=("shipments",),
                related_columns=("shipments.shipped_at", "shipments.delivered_at"),
            ),
            GlossaryTerm(
                "gross revenue",
                "Total order value before refunds.",
                "sum(orders.total_cents)",
                related_tables=("orders",),
                related_columns=("orders.total_cents",),
            ),
            GlossaryTerm(
                "net revenue",
                "Gross revenue minus succeeded refund amounts.",
                "sum(orders.total_cents) - sum(refunds.amount_cents)",
                related_tables=("orders", "payments", "refunds"),
                related_columns=("orders.total_cents", "refunds.amount_cents", "refunds.status"),
            ),
            GlossaryTerm(
                "refunded order",
                "An order with at least one succeeded refund through payment records.",
                "refunds.status = 'succeeded'",
                related_tables=("orders", "payments", "refunds"),
                related_columns=("refunds.status", "payments.order_id"),
            ),
        ),
    )


def fake_database_schema() -> DatabaseSchema:
    categories = table(
        "categories",
        ("category_id", "parent_category_id", "name"),
        (
            ForeignKeySchema(
                "commerce",
                "categories",
                ("parent_category_id",),
                "commerce",
                "categories",
                ("category_id",),
            ),
        ),
    )
    customers = table("customers", ("customer_id", "email", "full_name", "region", "country_code"))
    products = table(
        "products",
        ("product_id", "category_id", "sku", "name", "unit_price_cents", "active"),
        (
            ForeignKeySchema(
                "commerce",
                "products",
                ("category_id",),
                "commerce",
                "categories",
                ("category_id",),
            ),
        ),
    )
    orders = table(
        "orders",
        ("order_id", "customer_id", "ordered_at", "status", "billing_region", "total_cents"),
        (
            ForeignKeySchema(
                "commerce",
                "orders",
                ("customer_id",),
                "commerce",
                "customers",
                ("customer_id",),
            ),
        ),
    )
    order_items = table(
        "order_items",
        ("order_item_id", "order_id", "product_id", "quantity", "line_total_cents"),
        (
            ForeignKeySchema(
                "commerce",
                "order_items",
                ("order_id",),
                "commerce",
                "orders",
                ("order_id",),
            ),
            ForeignKeySchema(
                "commerce",
                "order_items",
                ("product_id",),
                "commerce",
                "products",
                ("product_id",),
            ),
        ),
    )
    payments = table(
        "payments",
        ("payment_id", "order_id", "payment_method", "status", "amount_cents"),
        (
            ForeignKeySchema(
                "commerce",
                "payments",
                ("order_id",),
                "commerce",
                "orders",
                ("order_id",),
            ),
        ),
    )
    refunds = table(
        "refunds",
        ("refund_id", "payment_id", "status", "reason", "amount_cents", "refunded_at"),
        (
            ForeignKeySchema(
                "commerce",
                "refunds",
                ("payment_id",),
                "commerce",
                "payments",
                ("payment_id",),
            ),
        ),
    )
    shipments = table(
        "shipments",
        ("shipment_id", "order_id", "carrier", "status", "shipped_at", "delivered_at"),
        (
            ForeignKeySchema(
                "commerce",
                "shipments",
                ("order_id",),
                "commerce",
                "orders",
                ("order_id",),
            ),
        ),
    )
    return DatabaseSchema(
        schemas=("commerce",),
        tables=(
            categories,
            customers,
            order_items,
            orders,
            payments,
            products,
            refunds,
            shipments,
        ),
    )


def table(
    name: str,
    column_names: tuple[str, ...],
    foreign_keys: tuple[ForeignKeySchema, ...] = (),
) -> TableSchema:
    return TableSchema(
        schema_name="commerce",
        name=name,
        columns=tuple(ColumnSchema(column_name, "TEXT", False) for column_name in column_names),
        primary_key=PrimaryKeySchema((column_names[0],), f"{name}_pkey"),
        foreign_keys=foreign_keys,
    )
