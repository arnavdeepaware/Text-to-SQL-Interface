from pathlib import Path

from app.core.config import Settings
from app.domain.evaluation import load_evaluation_dataset
from app.domain.glossary import BusinessGlossary
from app.domain.query_execution import QueryExecutionResult, QueryPlanSummary, QueryResultColumn
from app.domain.schema import ColumnSchema, DatabaseSchema, PrimaryKeySchema, TableSchema
from app.domain.schema_catalog import SchemaCatalog
from app.domain.sql_guardrails import ReferencedColumn, ReferencedTable, SQLValidationMetadata
from app.providers.scripted_sql_generation import ScriptedSQLGenerator, normalize_question
from app.services.evaluation import EvaluationRunner

DATASET_PATH = Path(__file__).resolve().parents[3] / "evals/cases/text_to_sql_v1.json"


def test_runner_scores_an_executed_case_from_result_semantics() -> None:
    dataset = load_evaluation_dataset(DATASET_PATH)
    case = next(item for item in dataset.cases if item.id == "order_lookup")
    assert case.fake_response is not None
    runner = EvaluationRunner(
        Settings(environment="test"),
        StaticCatalogProvider(),
        StaticExecutor(),
        ScriptedSQLGenerator({normalize_question(case.question): case.fake_response}),
    )

    report = runner.run(
        dataset.model_copy(update={"cases": [case]}),
        DATASET_PATH,
    )

    assert report.cases[0].passed is True
    assert report.cases[0].result_match is True
    assert report.cases[0].sql_exact_match is True


def test_runner_reports_generated_write_sql_as_blocked() -> None:
    dataset = load_evaluation_dataset(DATASET_PATH)
    case = next(item for item in dataset.cases if item.id == "generated_delete_blocked")
    assert case.fake_response is not None
    runner = EvaluationRunner(
        Settings(environment="test"),
        StaticCatalogProvider(),
        StaticExecutor(),
        ScriptedSQLGenerator({normalize_question(case.question): case.fake_response}),
    )

    report = runner.run(
        dataset.model_copy(update={"cases": [case]}),
        DATASET_PATH,
    )

    assert report.cases[0].passed is True
    assert report.cases[0].actual_outcome == "block"
    assert report.unsafe_query_escapes == 0


def test_runner_counts_missing_provider_response_as_infrastructure_failure() -> None:
    dataset = load_evaluation_dataset(DATASET_PATH)
    case = next(item for item in dataset.cases if item.id == "order_lookup")
    runner = EvaluationRunner(
        Settings(environment="test"),
        StaticCatalogProvider(),
        StaticExecutor(),
        ScriptedSQLGenerator({}),
    )

    report = runner.run(
        dataset.model_copy(update={"cases": [case]}),
        DATASET_PATH,
    )

    assert report.succeeded is False
    assert report.infrastructure_failures == 1
    assert report.cases[0].actual_outcome == "infrastructure_failure"


class StaticCatalogProvider:
    def get_schema(self, refresh: bool = False) -> SchemaCatalog:
        return SchemaCatalog(
            database_schema=DatabaseSchema(
                schemas=("commerce",),
                tables=(
                    TableSchema(
                        schema_name="commerce",
                        name="orders",
                        columns=(
                            ColumnSchema("order_id", "BIGINT", False),
                            ColumnSchema("order_number", "TEXT", False),
                            ColumnSchema("status", "TEXT", False),
                            ColumnSchema("total_cents", "INTEGER", False),
                        ),
                        primary_key=PrimaryKeySchema(("order_id",), "orders_pkey"),
                    ),
                ),
            ),
            samples=(),
            glossary=BusinessGlossary(version=1, terms=()),
            generated_at_epoch_seconds=0,
            cache_expires_at_epoch_seconds=99,
            refreshed=False,
        )


class StaticExecutor:
    def execute(self, sql: str, catalog: SchemaCatalog) -> QueryExecutionResult:
        return QueryExecutionResult(
            executed_sql=sql,
            columns=(QueryResultColumn("status"), QueryResultColumn("total_cents")),
            rows=({"status": "delivered", "total_cents": 12164},),
            row_count=1,
            execution_duration_ms=1,
            truncated=False,
            plan=QueryPlanSummary(
                estimated_rows=1,
                total_cost=1.0,
                plan_nodes=("Result",),
                referenced_relations=("commerce.orders",),
            ),
            guardrail_metadata=SQLValidationMetadata(
                statement_type="select",
                referenced_tables=(ReferencedTable("orders", "commerce", source="table"),),
                referenced_columns=(
                    ReferencedColumn(
                        "status",
                        table_identifier="commerce.orders",
                        source="table",
                    ),
                    ReferencedColumn(
                        "total_cents",
                        table_identifier="commerce.orders",
                        source="table",
                    ),
                    ReferencedColumn(
                        "order_number",
                        table_identifier="commerce.orders",
                        source="table",
                    ),
                ),
                effective_limit=1000,
            ),
        )
