from _pytest.monkeypatch import MonkeyPatch

from app.core.config import Settings
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
    assert result.sql.endswith("LIMIT 1000")
    assert result.metadata.effective_limit == 1000
    assert result.metadata.limit_was_added is True
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
    assert finding_rule_names(result) == {"SingleStatementRule"}


def test_semicolon_with_trailing_comment_trick_fails() -> None:
    result = validate(
        "SELECT order_id FROM commerce.orders; -- SELECT customer_id FROM commerce.customers"
    )

    assert not result.valid
    assert finding_codes(result) == {"multiple_statements"}


def test_non_select_statement_fails_structurally() -> None:
    result = validate("DELETE FROM commerce.orders WHERE status = 'cancelled'")

    assert not result.valid
    assert {"unsupported_statement_type", "blocked_statement_node"} <= finding_codes(result)
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


def test_existing_small_limit_is_preserved() -> None:
    result = validate("SELECT order_id FROM commerce.orders LIMIT 25")

    assert result.valid
    assert result.sql == "SELECT order_id FROM commerce.orders LIMIT 25"
    assert result.metadata.effective_limit == 25
    assert result.metadata.limit_was_added is False
    assert result.metadata.limit_was_reduced is False


def test_large_limit_is_reduced_through_ast() -> None:
    result = validate("SELECT order_id FROM commerce.orders LIMIT 50000")

    assert result.valid
    assert result.sql == "SELECT order_id FROM commerce.orders LIMIT 1000"
    assert result.metadata.effective_limit == 1000
    assert result.metadata.limit_was_reduced is True


def test_limit_rewrite_uses_configured_maximum() -> None:
    result = validate(
        "SELECT order_id FROM commerce.orders",
        Settings(environment="test", sql_guardrail_max_returned_rows=50),
    )

    assert result.valid
    assert result.sql == "SELECT order_id FROM commerce.orders LIMIT 50"
    assert result.metadata.effective_limit == 50


def test_unclassifiable_limit_fails_closed() -> None:
    result = validate("SELECT order_id FROM commerce.orders LIMIT ALL")

    assert not result.valid
    assert finding_codes(result) == {"unknown_column", "unclassifiable_limit"}
    assert "LimitRule" in finding_rule_names(result)


def test_max_subquery_depth_is_configurable() -> None:
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
        """,
        Settings(environment="test", sql_guardrail_max_subquery_depth=1),
    )

    assert not result.valid
    assert "subquery_depth_exceeded" in finding_codes(result)
    assert "MaxSubqueryDepthRule" in finding_rule_names(result)


def test_locking_clause_fails_closed() -> None:
    result = validate("SELECT order_id FROM commerce.orders FOR UPDATE")

    assert not result.valid
    assert finding_codes(result) == {"locking_clause_blocked"}
    assert finding_rule_names(result) == {"LockingClauseRule"}


def test_select_into_fails_closed() -> None:
    result = validate("SELECT order_id INTO temp_orders FROM commerce.orders")

    assert not result.valid
    assert "select_into_blocked" in finding_codes(result)


def test_transaction_control_fails_closed() -> None:
    result = validate("BEGIN")

    assert not result.valid
    assert {"unclassified_statement", "blocked_statement_node"} <= finding_codes(result)


def test_ddl_dml_and_privilege_statements_fail_closed() -> None:
    statements = (
        "INSERT INTO commerce.orders (order_id) VALUES (1)",
        "UPDATE commerce.orders SET status = 'paid'",
        "DELETE FROM commerce.orders",
        "MERGE INTO commerce.orders USING commerce.customers ON true WHEN MATCHED THEN DELETE",
        "CREATE TABLE x (id int)",
        "ALTER TABLE commerce.orders ADD COLUMN x int",
        "DROP TABLE commerce.orders",
        "TRUNCATE commerce.orders",
        "COPY commerce.orders TO STDOUT",
        "GRANT SELECT ON commerce.orders TO bob",
        "REVOKE SELECT ON commerce.orders FROM bob",
    )

    for statement in statements:
        result = validate(statement)
        assert not result.valid, statement
        assert finding_codes(result) & {
            "unsupported_statement_type",
            "unclassified_statement",
            "blocked_statement_node",
        }


def test_writable_cte_fails_closed() -> None:
    result = validate(
        """
        WITH hidden_write AS (
          UPDATE commerce.orders SET status = 'paid' RETURNING order_id
        )
        SELECT hidden_write.order_id
        FROM hidden_write
        """
    )

    assert not result.valid
    assert "blocked_statement_node" in finding_codes(result)
    assert "StructuralMutationRule" in finding_rule_names(result)


def test_nested_cte_with_unusual_casing_and_whitespace_passes() -> None:
    result = validate(
        """
        WITH "DeliveredOrders" AS (
            SELECT
                "o"."order_id",
                "o"."customer_id"
            FROM
                "commerce"."orders" AS "o"
            WHERE
                "o"."status" = 'delivered'
        ),
        totals AS (
            SELECT "DeliveredOrders"."customer_id", count(*) AS order_count
            FROM "DeliveredOrders"
            GROUP BY "DeliveredOrders"."customer_id"
        )
        SeLeCt totals.customer_id, totals.order_count
        FROM totals
        """
    )

    assert result.valid
    assert result.metadata.ctes == ("DeliveredOrders", "totals")
    assert result.sql.endswith("LIMIT 1000")


def test_comments_and_whitespace_cannot_hide_multiple_statements() -> None:
    result = validate(
        """
        SELECT order_id
        FROM commerce.orders
        /* harmless looking comment */;

        -- hidden second statement
        DELETE FROM commerce.orders
        """
    )

    assert not result.valid
    assert "multiple_statements" in finding_codes(result)


def test_policy_decision_logging_omits_sql_and_result_data(
    monkeypatch: MonkeyPatch,
) -> None:
    logged: list[tuple[str, dict[str, object]]] = []

    def fake_info(message: str, extra: dict[str, object]) -> None:
        logged.append((message, extra))

    monkeypatch.setattr("app.services.sql_guardrails.logger.info", fake_info)

    result = validate("SELECT order_id FROM commerce.orders")

    assert result.valid
    assert logged
    message, extra = logged[0]
    assert message == "Generated SQL policy decision"
    assert "sql" not in extra
    assert "result" not in extra
    assert extra["referenced_tables"] == ["commerce.orders"]


def validate(sql: str, settings: Settings | None = None) -> SQLValidationResult:
    return GeneratedSQLValidator(settings or Settings(environment="test")).validate(
        sql,
        fake_catalog(),
    )


def finding_codes(result: SQLValidationResult) -> set[str]:
    return {finding.code for finding in result.findings}


def finding_rule_names(result: SQLValidationResult) -> set[str]:
    return {finding.rule_name for finding in result.findings}


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
