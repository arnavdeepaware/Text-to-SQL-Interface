from app.core.config import Settings
from app.domain.glossary import BusinessGlossary, GlossaryTerm
from app.domain.prompt import FewShotExample, SQLGenerationPrompt
from app.domain.schema import (
    ColumnSchema,
    DatabaseSchema,
    ForeignKeySchema,
    PrimaryKeySchema,
    TableSchema,
)
from app.domain.schema_catalog import ColumnSample, SchemaCatalog
from app.services.prompt_engine import SchemaAwarePromptEngine
from app.services.schema_retrieval import LexicalSchemaRetriever


def test_revenue_prompt_is_focused_and_golden() -> None:
    prompt = build_prompt("Show sales by month")
    text = prompt.text

    assert prompt.original_question == "Show sales by month"
    assert prompt.sql_dialect == "PostgreSQL"
    assert prompt.selected_few_shot_ids == ("gross_revenue_by_month",)
    assert "Return structured JSON only with keys: sql, explanation" in text
    assert "The SQL must be read-only: SELECT statements only." in text
    assert "Original question:\nShow sales by month" in text
    assert "- commerce.orders" in text
    assert "total_cents TEXT not nullable" in text
    assert "billing_region TEXT not nullable; safe_samples=['Northeast', 'West']" in text
    assert "commerce.customers" not in text
    assert "commerce.refunds" not in text
    assert "DROP" in text


def test_net_revenue_prompt_includes_glossary_and_fk_paths() -> None:
    prompt = build_prompt("Calculate net revenue")
    text = prompt.text

    assert prompt.selected_few_shot_ids == ("net_revenue",)
    assert "- commerce.orders" in text
    assert "- commerce.payments" in text
    assert "- commerce.refunds" in text
    assert "net revenue: Gross revenue minus succeeded refund amounts." in text
    assert "commerce.payments.order_id -> commerce.orders.order_id" in text
    assert "commerce.refunds.payment_id -> commerce.payments.payment_id" in text
    assert "commerce.customers" not in text


def test_customer_category_prompt_preserves_bridge_path_and_excludes_refunds() -> None:
    prompt = build_prompt("Customers by category", min_table_score=25.0)
    text = prompt.text

    assert "- commerce.customers" in text
    assert "- commerce.categories" in text
    assert "- commerce.orders" in text
    assert "- commerce.order_items" in text
    assert "commerce.order_items.product_id -> commerce.products.product_id" in text
    assert "commerce.order_items.order_id -> commerce.orders.order_id" in text
    assert "commerce.orders.customer_id -> commerce.customers.customer_id" in text
    assert "commerce.refunds" not in text


def test_delivery_prompt_selects_relevant_few_shot_and_safe_samples() -> None:
    prompt = build_prompt("Average delivery time by carrier")
    text = prompt.text

    assert prompt.selected_few_shot_ids == ("delivery_time_by_carrier",)
    assert "- commerce.shipments" in text
    assert "carrier TEXT not nullable; safe_samples=['DHL', 'UPS']" in text
    assert (
        "delivery time: Time elapsed between shipment shipped_at and delivered_at timestamps."
        in text
    )
    assert "commerce.orders" not in text


def test_missing_glossary_prompt_still_contains_schema_context() -> None:
    catalog = fake_catalog(glossary=BusinessGlossary(version=1, terms=()))
    retrieval = LexicalSchemaRetriever(Settings(environment="test")).retrieve(
        "Refund amount by reason",
        catalog.database_schema,
        catalog.glossary,
    )

    prompt = SchemaAwarePromptEngine(Settings(environment="test")).build_prompt(
        "Refund amount by reason",
        catalog,
        retrieval,
    )

    assert "Business glossary: none selected" in prompt.text
    assert "- commerce.refunds" in prompt.text
    assert (
        "reason TEXT not nullable; safe_samples=['damaged_item', 'customer_return']"
        in prompt.text
    )


def test_unrelated_question_prompt_has_no_schema_context_or_few_shots() -> None:
    prompt = build_prompt("What is the weather forecast for tomorrow?")

    assert prompt.selected_few_shot_ids == ()
    assert "Tables: none" in prompt.text
    assert "Relationships: none selected" in prompt.text
    assert "Few-shot examples: none selected" in prompt.text


def test_prompt_context_budget_truncates_deterministically() -> None:
    first = build_prompt("Customers by category", min_table_score=25.0, budget_chars=500)
    second = build_prompt("Customers by category", min_table_score=25.0, budget_chars=500)

    assert first.text == second.text
    assert first.truncated is True
    assert first.context_chars == 500
    assert "[...prompt context truncated deterministically...]" in first.text
    assert "Return structured JSON only" in first.text


def test_prompt_safe_log_summary_excludes_prompt_text_and_secrets() -> None:
    prompt = build_prompt("Calculate net revenue")
    summary = prompt.safe_log_summary()

    assert "messages" not in summary
    assert "password" not in str(summary).casefold()
    assert summary["selected_few_shot_ids"] == ("net_revenue",)


def build_prompt(
    question: str,
    min_table_score: float = 8.0,
    budget_chars: int = 12_000,
) -> SQLGenerationPrompt:
    settings = Settings(
        environment="test",
        schema_retrieval_min_table_score=min_table_score,
        prompt_context_budget_chars=budget_chars,
    )
    catalog = fake_catalog()
    retrieval = LexicalSchemaRetriever(settings).retrieve(
        question,
        catalog.database_schema,
        catalog.glossary,
    )
    return SchemaAwarePromptEngine(settings).build_prompt(question, catalog, retrieval)


def fake_catalog(glossary: BusinessGlossary | None = None) -> SchemaCatalog:
    return SchemaCatalog(
        database_schema=fake_database_schema(),
        samples=(
            ColumnSample(
                table_identifier="commerce.orders",
                column_name="billing_region",
                values=("Northeast", "West"),
            ),
            ColumnSample(
                table_identifier="commerce.refunds",
                column_name="reason",
                values=("damaged_item", "customer_return"),
            ),
            ColumnSample(
                table_identifier="commerce.shipments",
                column_name="carrier",
                values=("DHL", "UPS"),
            ),
        ),
        glossary=glossary or fake_glossary(),
        generated_at_epoch_seconds=100.0,
        cache_expires_at_epoch_seconds=400.0,
        refreshed=False,
    )


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
    return DatabaseSchema(
        schemas=("commerce",),
        tables=(
            table(
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
            ),
            table("customers", ("customer_id", "email", "full_name", "region", "country_code")),
            table(
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
            ),
            table(
                "orders",
                (
                    "order_id",
                    "customer_id",
                    "ordered_at",
                    "status",
                    "billing_region",
                    "total_cents",
                ),
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
            ),
            table(
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
            ),
            table(
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
            ),
            table(
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
            ),
            table(
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
            ),
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


def test_prompt_engine_uses_injected_few_shots_without_resource_loading() -> None:
    custom_example = FewShotExample(
        example_id="custom_orders",
        question="Custom sales question",
        sql="SELECT sum(orders.total_cents) FROM commerce.orders AS orders;",
        required_tables=("orders",),
        required_columns=("orders.total_cents",),
        tags=("sales",),
    )
    settings = Settings(environment="test")
    catalog = fake_catalog()
    retrieval = LexicalSchemaRetriever(settings).retrieve(
        "Show sales by month",
        catalog.database_schema,
        catalog.glossary,
    )

    prompt = SchemaAwarePromptEngine(settings, few_shot_examples=(custom_example,)).build_prompt(
        "Show sales by month",
        catalog,
        retrieval,
    )

    assert prompt.selected_few_shot_ids == ("custom_orders",)
