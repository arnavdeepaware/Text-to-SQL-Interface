from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import sqlglot

from app.core.config import Settings
from app.domain.evaluation import EvaluationCase, EvaluationDataset
from app.domain.query_execution import QueryExecutionResult
from app.providers.sql_generation import SQLGenerationError, SQLGenerator
from app.services.evaluation_results import compare_expected_result
from app.services.query_execution import QueryExecutionError, QueryPlanInspectionError
from app.services.query_workflow import QueryExecutor, QueryWorkflowService, SchemaCatalogProvider
from app.services.sql_guardrails import SQLGuardrailValidationError


@dataclass(frozen=True)
class EvaluationCaseReport:
    case_id: str
    expected_outcome: str
    actual_outcome: str
    passed: bool
    sql_exact_match: bool | None = None
    result_match: bool | None = None
    result_match_reason: str | None = None
    tables_match: bool | None = None
    columns_match: bool | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class EvaluationRunReport:
    dataset_name: str
    dataset_version: int
    dataset_sha256: str
    provider: str
    cases: tuple[EvaluationCaseReport, ...]
    infrastructure_failures: int

    @property
    def passed_cases(self) -> int:
        return sum(case.passed for case in self.cases)

    @property
    def failed_cases(self) -> int:
        return len(self.cases) - self.passed_cases

    @property
    def result_match_rate(self) -> float | None:
        matches = [case.result_match for case in self.cases if case.result_match is not None]
        return None if not matches else round(sum(matches) / len(matches), 4)

    @property
    def sql_exact_match_rate(self) -> float | None:
        matches = [case.sql_exact_match for case in self.cases if case.sql_exact_match is not None]
        return None if not matches else round(sum(matches) / len(matches), 4)

    @property
    def unsafe_query_escapes(self) -> int:
        return sum(
            case.expected_outcome == "block" and case.actual_outcome == "execute"
            for case in self.cases
        )

    @property
    def succeeded(self) -> bool:
        return self.failed_cases == 0 and self.infrastructure_failures == 0

    def json_payload(self) -> dict[str, Any]:
        return {
            "dataset": {
                "name": self.dataset_name,
                "version": self.dataset_version,
                "sha256": self.dataset_sha256,
            },
            "provider": self.provider,
            "summary": {
                "total_cases": len(self.cases),
                "passed_cases": self.passed_cases,
                "failed_cases": self.failed_cases,
                "infrastructure_failures": self.infrastructure_failures,
                "result_match_rate": self.result_match_rate,
                "sql_exact_match_rate": self.sql_exact_match_rate,
                "unsafe_query_escapes": self.unsafe_query_escapes,
                "succeeded": self.succeeded,
            },
            "cases": [asdict(case) for case in self.cases],
        }


class EvaluationRunner:
    """Run versioned cases through the existing guarded Text-to-SQL workflow."""

    def __init__(
        self,
        settings: Settings,
        catalog_provider: SchemaCatalogProvider,
        query_executor: QueryExecutor,
        sql_generator: SQLGenerator,
        provider_name: str = "fake",
    ) -> None:
        self._settings = settings
        self._catalog_provider = catalog_provider
        self._query_executor = query_executor
        self._sql_generator = sql_generator
        self._provider_name = provider_name

    def run(self, dataset: EvaluationDataset, dataset_path: Path) -> EvaluationRunReport:
        reports: list[EvaluationCaseReport] = []
        infrastructure_failures = 0
        for case in dataset.cases:
            report = self._run_case(case)
            reports.append(report)
            if report.actual_outcome == "infrastructure_failure":
                infrastructure_failures += 1
        return EvaluationRunReport(
            dataset_name=dataset.name,
            dataset_version=dataset.version,
            dataset_sha256=sha256_file(dataset_path),
            provider=self._provider_name,
            cases=tuple(reports),
            infrastructure_failures=infrastructure_failures,
        )

    def _run_case(self, case: EvaluationCase) -> EvaluationCaseReport:
        workflow = QueryWorkflowService(
            settings=self._settings,
            catalog_provider=self._catalog_provider,
            sql_generator=self._sql_generator,
            query_executor=self._query_executor,
            request_id=f"eval-{case.id}",
        )
        try:
            result = workflow.run(case.question)
        except SQLGuardrailValidationError as exc:
            return EvaluationCaseReport(
                case_id=case.id,
                expected_outcome=case.expected_outcome,
                actual_outcome="block",
                passed=case.expected_outcome == "block",
                error_code=exc.public_code,
            )
        except QueryPlanInspectionError as exc:
            return EvaluationCaseReport(
                case_id=case.id,
                expected_outcome=case.expected_outcome,
                actual_outcome="block",
                passed=case.expected_outcome == "block",
                error_code=exc.public_code,
            )
        except (SQLGenerationError, QueryExecutionError) as exc:
            return EvaluationCaseReport(
                case_id=case.id,
                expected_outcome=case.expected_outcome,
                actual_outcome="infrastructure_failure",
                passed=False,
                error_code=exc.public_code,
            )

        if result.clarification is not None:
            return EvaluationCaseReport(
                case_id=case.id,
                expected_outcome=case.expected_outcome,
                actual_outcome="clarify",
                passed=case.expected_outcome == "clarify",
            )
        if result.execution is None or result.draft is None:
            return EvaluationCaseReport(
                case_id=case.id,
                expected_outcome=case.expected_outcome,
                actual_outcome="infrastructure_failure",
                passed=False,
                error_code="query_execution_missing_result",
            )
        return execution_report(case, result.execution, result.draft.result.sql)


def execution_report(
    case: EvaluationCase,
    execution: QueryExecutionResult,
    drafted_sql: str | None,
) -> EvaluationCaseReport:
    expected_result = case.expected_result
    if expected_result is None or case.expected_sql is None:
        return EvaluationCaseReport(
            case_id=case.id,
            expected_outcome=case.expected_outcome,
            actual_outcome="execute",
            passed=False,
            error_code="missing_execution_expectation",
        )
    result_comparison = compare_expected_result(expected_result, execution)
    tables_match, columns_match = references_match(case, execution)
    sql_exact_match = normalized_sql(drafted_sql) == normalized_sql(case.expected_sql)
    passed = (
        case.expected_outcome == "execute"
        and result_comparison.matched == case.expected_result_match
        and tables_match
        and columns_match
    )
    return EvaluationCaseReport(
        case_id=case.id,
        expected_outcome=case.expected_outcome,
        actual_outcome="execute",
        passed=passed,
        sql_exact_match=sql_exact_match,
        result_match=result_comparison.matched,
        result_match_reason=result_comparison.reason,
        tables_match=tables_match,
        columns_match=columns_match,
    )


def references_match(case: EvaluationCase, execution: QueryExecutionResult) -> tuple[bool, bool]:
    metadata = execution.guardrail_metadata
    if metadata is None:
        return False, False
    actual_tables = {
        table.identifier
        for table in metadata.referenced_tables
        if table.source == "table"
    }
    actual_columns = {
        column.identifier
        for column in metadata.referenced_columns
        if column.table_identifier is not None
    }
    return set(case.expected_tables) <= actual_tables, set(case.expected_columns) <= actual_columns


def normalized_sql(sql: str | None) -> str | None:
    if sql is None:
        return None
    try:
        return sqlglot.parse_one(sql, read="postgres").sql(dialect="postgres")
    except sqlglot.errors.ParseError:
        return " ".join(sql.casefold().split())


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_reports(report: EvaluationRunReport, report_directory: Path) -> tuple[Path, Path]:
    """Write transient JSON and Markdown reports with deterministic content."""

    report_directory.mkdir(parents=True, exist_ok=True)
    json_path = report_directory / "latest.json"
    markdown_path = report_directory / "latest.md"
    json_path.write_text(
        json.dumps(report.json_payload(), indent=2, sort_keys=True) + "\n",
        "utf-8",
    )
    markdown_path.write_text(render_markdown_report(report), "utf-8")
    return json_path, markdown_path


def render_markdown_report(report: EvaluationRunReport) -> str:
    summary = report.json_payload()["summary"]
    lines = [
        "# Text-to-SQL Evaluation Report",
        "",
        f"Dataset: `{report.dataset_name}` v{report.dataset_version}",
        f"Provider: `{report.provider}`",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for key, value in summary.items():
        lines.append(f"| {key} | {value} |")
    lines.extend(
        (
            "",
            "| Case | Expected | Actual | Passed | Result match | SQL exact |",
            "| --- | --- | --- | --- | --- | --- |",
        )
    )
    for case in report.cases:
        lines.append(
            f"| {case.case_id} | {case.expected_outcome} | {case.actual_outcome} | "
            f"{case.passed} | {case.result_match} | {case.sql_exact_match} |"
        )
    return "\n".join(lines) + "\n"
