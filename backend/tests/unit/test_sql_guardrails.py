from app.domain.glossary import BusinessGlossary
from app.domain.schema import ColumnSchema, DatabaseSchema, PrimaryKeySchema, TableSchema
from app.domain.schema_catalog import SchemaCatalog
from app.domain.sql_guardrails import SQLValidationResult
from app.services.sql_guardrails import GeneratedSQLValidator


def test_complex_join_with_aliases_passes_and_extracts_references() -> None:
    result = validate(
        """
        SELECT
          o.order_id,
          c.region,
          sum(oi.line_total_cents) AS revenue_cents
        FROM commerce.orders AS o
        JOIN commerce.customers AS c ON c.customer_id = o.customer_id
        JOIN commerce.order_items AS oi ON oi.order_id = o.order_id
        WHERE o.status = 'delivered'
        GROUP BY o.order_id, c.region
        ORDER BY revenue_cents DESC
        """
    )

    assert result.valid
    assert result.metadata.statement_type == "select"
    assert {table.identifier for table in result.metadata.referenced_tables} == {
        "commerce.orders",
        "commerce.customers",
        "commerce.order_items",
    }
    assert {"o", "c", "oi", "revenue_cents"} <= set(result.metadata.aliases)
    assert result.metadata.functions == ("sum",)
    assert {
        column.identifier
        for column in result.metadata.referenced_columns
        if column.table_identifier is not None
    } >= {
        "commerce.orders.order_id",
        "commerce.orders.customer_id",
        "commerce.customers.customer_id",
        "commerce.customers.region",
        "commerce.order_items.order_id",
        "commerce.order_items.line_total_cents",
    }


def test_cte_with_aggregate_passes_and_extracts_cte_columns() -> None:
    result = validate(
        """
        WITH monthly AS (
          SELECT
            date_trunc('month', o.ordered_at) AS order_month,
            sum(o.total_cents) AS gross_revenue_cents
          FROM commerce.orders AS o
          GROUP BY 1
        )
        SELECT monthly.order_month, monthly.gross_revenue_cents
        FROM monthly
        ORDER BY monthly.order_month
        """
    )

    assert result.valid
    assert result.metadata.ctes == ("monthly",)
    assert result.metadata.functions == ("date_trunc", "sum")
    assert any(
        table.name == "monthly" and table.source == "cte"
        for table in result.metadata.referenced_tables
    )
    assert {
        column.identifier
        for column in result.metadata.referenced_columns
        if column.source == "cte"
    } == {"monthly.order_month", "monthly.gross_revenue_cents"}


def test_nested_subqueries_pass_and_report_depth() -> None:
    result = validate(
        """
        SELECT o.order_id
        FROM commerce.orders AS o
        WHERE o.customer_id IN (
          SELECT c.customer_id
          FROM commerce.customers AS c
          WHERE c.region IN (
            SELECT c2.region
            FROM commerce.customers AS c2
            WHERE c2.country_code = 'US'
          )
        )
        """
    )

    assert result.valid
    assert result.metadata.subquery_depth == 2
    assert {table.alias for table in result.metadata.referenced_tables} >= {"o", "c", "c2"}


def test_qualified_and_aliased_identifiers_resolve_correctly() -> None:
    result = validate(
        """
        SELECT orders.order_id, customers.region
        FROM commerce.orders
        JOIN commerce.customers
          ON customers.customer_id = orders.customer_id
        """
    )

    assert result.valid
    assert not result.findings


def test_quoted_identifiers_matching_schema_pass() -> None:
    result = validate('SELECT "o"."order_id" FROM "commerce"."orders" AS "o"')

    assert result.valid
    assert {column.identifier for column in result.metadata.referenced_columns} == {
        "commerce.orders.order_id"
    }


def test_comments_do_not_prevent_valid_select() -> None:
    result = validate(
        """
        SELECT /* delete from commerce.orders; */ o.order_id
        FROM commerce.orders AS o
        WHERE o.status = 'delivered'
        """
    )

    assert result.valid


def test_empty_sql_fails() -> None:
    result = validate("   \n\t ")

    assert not result.valid
    assert finding_codes(result) == {"empty_sql"}


def test_malformed_sql_fails() -> None:
    result = validate("SELECT FROM")

    assert not result.valid
    assert finding_codes(result) == {"malformed_sql"}


def test_multiple_statements_fail() -> None:
    result = validate(
        "SELECT order_id FROM commerce.orders; SELECT customer_id FROM commerce.customers"
    )

    assert not result.valid
    assert finding_codes(result) == {"multiple_statements"}


def test_semicolon_with_trailing_comment_trick_fails() -> None:
    result = validate(
        "SELECT order_id FROM commerce.orders; -- SELECT customer_id FROM commerce.customers"
    )

    assert not result.valid
    assert finding_codes(result) == {"multiple_statements"}


def test_non_select_statement_fails_structurally() -> None:
    result = validate("DELETE FROM commerce.orders WHERE status = 'cancelled'")

    assert not result.valid
    assert {"unsupported_statement_type", "unsafe_statement_node"} <= finding_codes(result)
    assert result.metadata.statement_type == "delete"


def test_invented_table_fails_schema_validation() -> None:
    result = validate("SELECT total_cents FROM commerce.invoices")

    assert not result.valid
    assert "unknown_table" in finding_codes(result)


def test_invented_column_fails_schema_validation() -> None:
    result = validate("SELECT o.secret_margin FROM commerce.orders AS o")

    assert not result.valid
    assert finding_codes(result) == {"unknown_column"}


def test_ambiguous_unqualified_column_fails() -> None:
    result = validate(
        """
        SELECT customer_id
        FROM commerce.orders
        JOIN commerce.customers
          ON customers.customer_id = orders.customer_id
        """
    )

    assert not result.valid
    assert "ambiguous_column" in finding_codes(result)


def test_case_sensitive_quoted_identifier_must_match_schema() -> None:
    result = validate('SELECT "O"."Order_ID" FROM "commerce"."orders" AS "O"')

    assert not result.valid
    assert finding_codes(result) == {"unknown_column"}


def validate(sql: str) -> SQLValidationResult:
    return GeneratedSQLValidator().validate(sql, fake_catalog())


def finding_codes(result: SQLValidationResult) -> set[str]:
    return {finding.code for finding in result.findings}


def fake_catalog() -> SchemaCatalog:
    return SchemaCatalog(
        database_schema=DatabaseSchema(
            schemas=("commerce",),
            tables=(
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
                ),
                table("customers", ("customer_id", "region", "country_code")),
                table(
                    "order_items",
                    ("order_item_id", "order_id", "product_id", "line_total_cents"),
                ),
                table("products", ("product_id", "category_id", "name")),
                table("categories", ("category_id", "name")),
                table("payments", ("payment_id", "order_id", "status")),
                table("refunds", ("refund_id", "payment_id", "status", "amount_cents")),
            ),
        ),
        samples=(),
        glossary=BusinessGlossary(version=1, terms=()),
        generated_at_epoch_seconds=0,
        cache_expires_at_epoch_seconds=0,
        refreshed=False,
    )


def table(name: str, columns: tuple[str, ...]) -> TableSchema:
    return TableSchema(
        schema_name="commerce",
        name=name,
        columns=tuple(ColumnSchema(column, "TEXT", False) for column in columns),
        primary_key=PrimaryKeySchema((columns[0],), f"{name}_pkey"),
    )
