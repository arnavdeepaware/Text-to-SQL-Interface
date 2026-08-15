from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import sqlglot

from app.core.config import Settings
from app.domain.evaluation import EvaluationCase, EvaluationDataset, RegressionThresholds
from app.domain.query_execution import QueryExecutionResult
from app.domain.schema_catalog import SchemaCatalog
from app.providers.sql_generation import SQLGenerationError, SQLGenerator
from app.services.evaluation_results import compare_expected_result
from app.services.query_draft import detect_business_ambiguity
from app.services.query_execution import QueryExecutionError, QueryPlanInspectionError
from app.services.query_workflow import (
    QueryExecutor,
    QueryWorkflowResult,
    QueryWorkflowService,
    QueryWorkflowValidationError,
    SchemaCatalogProvider,
)
from app.services.sql_guardrails import SQLGuardrailValidationError


@dataclass(frozen=True)
class EvaluationCaseReport:
    case_id: str
    answerability: str
    guardrail: str
    hallucination: str
    ambiguity_expected: bool
    expected_outcome: str
    actual_outcome: str
    passed: bool
    sql_exact_match: bool | None = None
    result_match: bool | None = None
    result_match_reason: str | None = None
    tables_match: bool | None = None
    columns_match: bool | None = None
    ambiguity_detected: bool | None = None
    hallucination_detected: bool | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class EvaluationRunReport:
    dataset_name: str
    dataset_version: int
    dataset_sha256: str
    provider: str
    thresholds: RegressionThresholds
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
            case.guardrail == "block_generated_sql" and case.actual_outcome == "execute"
            for case in self.cases
        )

    @property
    def ambiguity_detection_accuracy(self) -> float | None:
        eligible = [
            case
            for case in self.cases
            if case.guardrail == "allow"
            and case.answerability in {"ambiguous", "unsupported"}
            and case.ambiguity_detected is not None
        ]
        if not eligible:
            return None
        return round(
            sum(
                case.ambiguity_detected == case.ambiguity_expected
                for case in eligible
            )
            / len(eligible),
            4,
        )

    @property
    def unanswerable_handling_rate(self) -> float | None:
        eligible = [
            case
            for case in self.cases
            if case.answerability == "unsupported" and case.guardrail == "allow"
        ]
        if not eligible:
            return None
        return round(sum(case.actual_outcome == "clarify" for case in eligible) / len(eligible), 4)

    @property
    def hallucination_precision(self) -> float | None:
        matrix = hallucination_matrix(self.cases)
        if matrix is None or matrix["predicted_positive"] == 0:
            return None
        return round(matrix["true_positive"] / matrix["predicted_positive"], 4)

    @property
    def hallucination_recall(self) -> float | None:
        matrix = hallucination_matrix(self.cases)
        if matrix is None or matrix["actual_positive"] == 0:
            return None
        return round(matrix["true_positive"] / matrix["actual_positive"], 4)

    @property
    def guardrail_effectiveness(self) -> float | None:
        eligible = [
            case for case in self.cases if case.guardrail == "block_generated_sql"
        ]
        if not eligible:
            return None
        return round(sum(case.actual_outcome == "block" for case in eligible) / len(eligible), 4)

    @property
    def succeeded(self) -> bool:
        return (
            self.failed_cases == 0
            and self.infrastructure_failures <= self.thresholds.max_infrastructure_failures
            and len(self.cases) >= self.thresholds.minimum_cases
            and self.unsafe_query_escapes <= self.thresholds.max_unsafe_query_escapes
        )

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
                "ambiguity_detection_accuracy": self.ambiguity_detection_accuracy,
                "unanswerable_handling_rate": self.unanswerable_handling_rate,
                "hallucination_precision": self.hallucination_precision,
                "hallucination_recall": self.hallucination_recall,
                "guardrail_effectiveness": self.guardrail_effectiveness,
                "unsafe_query_escapes": self.unsafe_query_escapes,
                "succeeded": self.succeeded,
            },
            "regression_thresholds": self.thresholds.model_dump(),
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
            dataset_sha256=sha256_dataset(dataset),
            provider=self._provider_name,
            thresholds=dataset.regression_thresholds,
            cases=tuple(reports),
            infrastructure_failures=infrastructure_failures,
        )

    def _run_case(self, case: EvaluationCase) -> EvaluationCaseReport:
        catalog = self._catalog_provider.get_schema()
        ambiguity_detected = (
            detect_business_ambiguity(case.question, catalog.glossary) is not None
            if case.guardrail == "allow"
            else None
        )
        workflow = QueryWorkflowService(
            settings=self._settings,
            catalog_provider=StaticCatalogProvider(catalog),
            sql_generator=self._sql_generator,
            query_executor=self._query_executor,
            request_id=f"eval-{case.id}",
        )
        try:
            result = workflow.run(case.question)
        except SQLGuardrailValidationError as exc:
            return EvaluationCaseReport(
                case_id=case.id,
                answerability=case.answerability,
                guardrail=case.guardrail,
                hallucination=case.hallucination,
                ambiguity_expected=case.ambiguity,
                expected_outcome=case.expected_outcome,
                actual_outcome="block",
                passed=case.expected_outcome == "block",
                error_code=exc.public_code,
                ambiguity_detected=ambiguity_detected,
                hallucination_detected=case.hallucination == "schema_reference",
            )
        except QueryPlanInspectionError as exc:
            return EvaluationCaseReport(
                case_id=case.id,
                answerability=case.answerability,
                guardrail=case.guardrail,
                hallucination=case.hallucination,
                ambiguity_expected=case.ambiguity,
                expected_outcome=case.expected_outcome,
                actual_outcome="block",
                passed=case.expected_outcome == "block",
                error_code=exc.public_code,
                ambiguity_detected=ambiguity_detected,
            )
        except (SQLGenerationError, QueryExecutionError) as exc:
            return EvaluationCaseReport(
                case_id=case.id,
                answerability=case.answerability,
                guardrail=case.guardrail,
                hallucination=case.hallucination,
                ambiguity_expected=case.ambiguity,
                expected_outcome=case.expected_outcome,
                actual_outcome="infrastructure_failure",
                passed=False,
                error_code=exc.public_code,
                ambiguity_detected=ambiguity_detected,
            )
        except QueryWorkflowValidationError as exc:
            return EvaluationCaseReport(
                case_id=case.id,
                answerability=case.answerability,
                guardrail=case.guardrail,
                hallucination=case.hallucination,
                ambiguity_expected=case.ambiguity,
                expected_outcome=case.expected_outcome,
                actual_outcome="block",
                passed=case.expected_outcome == "block",
                error_code=exc.public_code,
            )

        if result.clarification is not None:
            return EvaluationCaseReport(
                case_id=case.id,
                answerability=case.answerability,
                guardrail=case.guardrail,
                hallucination=case.hallucination,
                ambiguity_expected=case.ambiguity,
                expected_outcome=case.expected_outcome,
                actual_outcome="clarify",
                passed=case.expected_outcome == "clarify",
                ambiguity_detected=ambiguity_detected,
            )
        if result.execution is None or result.draft is None:
            return EvaluationCaseReport(
                case_id=case.id,
                answerability=case.answerability,
                guardrail=case.guardrail,
                hallucination=case.hallucination,
                ambiguity_expected=case.ambiguity,
                expected_outcome=case.expected_outcome,
                actual_outcome="infrastructure_failure",
                passed=False,
                error_code="query_execution_missing_result",
                ambiguity_detected=ambiguity_detected,
            )
        return execution_report(
            case,
            result.execution,
            result.draft.result.sql,
            ambiguity_detected,
            hallucination_detected(result),
        )


def execution_report(
    case: EvaluationCase,
    execution: QueryExecutionResult,
    drafted_sql: str | None,
    ambiguity_detected: bool | None,
    hallucination_detected: bool,
) -> EvaluationCaseReport:
    expected_result = case.expected_result
    if expected_result is None or case.expected_sql is None:
        return EvaluationCaseReport(
            case_id=case.id,
            answerability=case.answerability,
            guardrail=case.guardrail,
            hallucination=case.hallucination,
            ambiguity_expected=case.ambiguity,
            expected_outcome=case.expected_outcome,
            actual_outcome="execute",
            passed=False,
            error_code="missing_execution_expectation",
            ambiguity_detected=ambiguity_detected,
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
        answerability=case.answerability,
        guardrail=case.guardrail,
        hallucination=case.hallucination,
        ambiguity_expected=case.ambiguity,
        expected_outcome=case.expected_outcome,
        actual_outcome="execute",
        passed=passed,
        sql_exact_match=sql_exact_match,
        result_match=result_comparison.matched,
        result_match_reason=result_comparison.reason,
        tables_match=tables_match,
        columns_match=columns_match,
        ambiguity_detected=ambiguity_detected,
        hallucination_detected=hallucination_detected,
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


def sha256_dataset(dataset: EvaluationDataset) -> str:
    payload = json.dumps(dataset.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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
        "This is deterministic scripted-provider evidence. Live-model runs require explicit opt-in "
        "and are exploratory; SQL exact match is diagnostic while result matching is primary.",
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


class StaticCatalogProvider:
    def __init__(self, catalog: SchemaCatalog) -> None:
        self._catalog = catalog

    def get_schema(self, refresh: bool = False) -> SchemaCatalog:
        return self._catalog


def hallucination_detected(result: QueryWorkflowResult) -> bool:
    signals = result.validation_signals
    return any(signal.status in {"warning", "failed"} for signal in signals)


def hallucination_matrix(cases: tuple[EvaluationCaseReport, ...]) -> dict[str, int] | None:
    eligible = [case for case in cases if case.hallucination_detected is not None]
    if not eligible:
        return None
    actual_positive = sum(case.hallucination not in {"none", "not_assessed"} for case in eligible)
    predicted_positive = sum(case.hallucination_detected is True for case in eligible)
    true_positive = sum(
        case.hallucination not in {"none", "not_assessed"}
        and case.hallucination_detected is True
        for case in eligible
    )
    return {
        "actual_positive": actual_positive,
        "predicted_positive": predicted_positive,
        "true_positive": true_positive,
    }
