from __future__ import annotations

import argparse
import os
from pathlib import Path

from app.core.config import Settings
from app.db.engine import create_database_engine
from app.domain.evaluation import load_evaluation_dataset
from app.providers.openai_sql_generation import OpenAISQLGenerator
from app.providers.scripted_sql_generation import ScriptedSQLGenerator, normalize_question
from app.providers.sql_generation import SQLGenerator
from app.services.evaluation import EvaluationRunner, write_reports
from app.services.query_execution import QueryExecutionService
from app.services.schema_catalog import SchemaCatalogService


def main() -> int:
    parser = argparse.ArgumentParser(description="Run versioned Text-to-SQL evaluations.")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--reports", type=Path, required=True)
    parser.add_argument("--provider", choices=("fake", "openai"), default="fake")
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    dataset = load_evaluation_dataset(args.dataset)
    if args.validate_only:
        print(f"Validated {len(dataset.cases)} cases in {args.dataset}")
        return 0
    if args.provider == "openai" and (
        not args.allow_live or os.environ.get("TEXT_TO_SQL_EVAL_ALLOW_LIVE") != "true"
    ):
        parser.error("live evaluation requires --allow-live and TEXT_TO_SQL_EVAL_ALLOW_LIVE=true")

    settings = Settings(
        environment="test",
        query_history_enabled=False,
        confidence_semantic_enabled=False,
        confidence_multi_query_enabled=False,
    )
    generator: SQLGenerator
    if args.provider == "fake":
        responses = {
            normalize_question(case.question): case.fake_response
            for case in dataset.cases
            if case.fake_response is not None
        }
        generator = ScriptedSQLGenerator(responses=responses)
    else:
        generator = OpenAISQLGenerator(settings)

    engine = create_database_engine(settings)
    try:
        catalog = SchemaCatalogService(engine, settings)
        runner = EvaluationRunner(
            settings,
            catalog,
            QueryExecutionService(engine, settings),
            generator,
            provider_name=args.provider,
        )
        report = runner.run(dataset, args.dataset)
        json_path, markdown_path = write_reports(report, args.reports)
    finally:
        engine.dispose()
    print(f"Wrote {json_path} and {markdown_path}")
    if report.infrastructure_failures:
        return 2
    return 0 if report.succeeded else 1


if __name__ == "__main__":
    raise SystemExit(main())
