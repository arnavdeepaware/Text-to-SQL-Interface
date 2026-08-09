from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from time import perf_counter
from typing import Literal, Protocol

import sqlglot
from sqlglot.errors import ParseError

from app.core.config import Settings
from app.domain.confidence import ValidationSignal
from app.domain.prompt import PromptMessage, SQLGenerationPrompt
from app.domain.query_execution import QueryExecutionResult
from app.domain.schema_catalog import SchemaCatalog
from app.domain.schema_retrieval import SchemaRetrievalResult
from app.domain.sql_generation import SQLGenerationDraft
from app.providers.sql_generation import SQLGenerationError, SQLGenerator
from app.services.prompt_engine import SchemaAwarePromptEngine
from app.services.query_execution import QueryExecutionError, QueryPlanInspectionError
from app.services.result_equivalence import ResultComparison, compare_result_sets
from app.services.sql_guardrails import POSTGRES_DIALECT, SQLGuardrailValidationError

ComplexityClass = Literal["simple_lookup", "aggregate", "grouped_comparison", "join_sensitive"]


class QueryExecutor(Protocol):
    def execute(self, sql: str, catalog: SchemaCatalog) -> QueryExecutionResult: ...


@dataclass(frozen=True)
class QueryComplexity:
    classification: ComplexityClass
    eligible: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class MultiQueryAgreementRequest:
    """Inputs for independent alternate SQL generation and result agreement."""

    question: str
    catalog: SchemaCatalog
    retrieval: SchemaRetrievalResult | None
    primary_draft: SQLGenerationDraft
    primary_execution: QueryExecutionResult
    validation_signals: tuple[ValidationSignal, ...] = ()


class QueryComplexityClassifier:
    """Decide whether multi-query validation adds evidence worth its cost."""

    def classify(self, request: MultiQueryAgreementRequest) -> QueryComplexity:
        metadata = request.primary_execution.guardrail_metadata
        if metadata is None:
            return QueryComplexity(
                "simple_lookup",
                False,
                ("metadata_unavailable",),
            )

        tokens = tokenize(request.question)
        functions = set(metadata.functions)
        table_count = len(
            {
                table.identifier
                for table in metadata.referenced_tables
                if table.source == "table"
            }
        )
        reasons: list[str] = []
        if functions & AGGREGATE_FUNCTIONS:
            reasons.append("aggregate_function")
        if tokens & GROUPING_TERMS:
            reasons.append("grouping_or_comparison_term")
        if tokens & METRIC_TERMS:
            reasons.append("metric_term")
        if table_count > 1:
            reasons.append("multiple_tables")

        if "aggregate_function" in reasons and "grouping_or_comparison_term" in reasons:
            return QueryComplexity("grouped_comparison", True, tuple(reasons))
        if "aggregate_function" in reasons or "metric_term" in reasons:
            return QueryComplexity("aggregate", True, tuple(reasons))
        if table_count > 1 and tokens & JOIN_SENSITIVE_TERMS:
            return QueryComplexity("join_sensitive", True, tuple(reasons))
        return QueryComplexity("simple_lookup", False, tuple(reasons) or ("simple_shape",))


class MultiQueryAgreementService:
    """Generate one independent alternate SQL draft and compare guarded results."""

    def __init__(
        self,
        settings: Settings,
        sql_generator: SQLGenerator,
        query_executor: QueryExecutor,
        prompt_engine: SchemaAwarePromptEngine | None = None,
        classifier: QueryComplexityClassifier | None = None,
    ) -> None:
        self._settings = settings
        self._sql_generator = sql_generator
        self._query_executor = query_executor
        self._prompt_engine = prompt_engine or SchemaAwarePromptEngine(settings)
        self._classifier = classifier or QueryComplexityClassifier()

    def evaluate(self, request: MultiQueryAgreementRequest) -> tuple[ValidationSignal, ...]:
        if not self._settings.confidence_multi_query_enabled:
            return ()
        if self._settings.confidence_multi_query_max_alternates < 1:
            return (
                not_applicable_signal(
                    "multi_query_disabled_by_budget",
                    "Multi-query validation is disabled because no alternates are allowed.",
                ),
            )

        failed_deterministic_codes = tuple(
            signal.code for signal in request.validation_signals if signal.status == "failed"
        )
        if failed_deterministic_codes:
            return (
                not_applicable_signal(
                    "multi_query_skipped_deterministic_failure",
                    "Multi-query validation was skipped because deterministic validation failed.",
                    {"failed_signal_codes": failed_deterministic_codes},
                ),
            )

        complexity = self._classifier.classify(request)
        if not complexity.eligible:
            return (
                not_applicable_signal(
                    "multi_query_not_applicable_simple_lookup",
                    "Multi-query validation is not warranted for this query shape.",
                    complexity_evidence(complexity),
                ),
            )
        if request.retrieval is None:
            return (
                unavailable_signal(
                    "multi_query_retrieval_unavailable",
                    "Multi-query validation could not build an independent prompt.",
                    complexity_evidence(complexity),
                ),
            )
        if request.primary_execution.truncated or (
            request.primary_execution.row_count
            > self._settings.confidence_multi_query_max_result_rows
        ):
            return (
                not_applicable_signal(
                    "multi_query_primary_result_too_large",
                    "Multi-query validation skipped comparison because the primary result "
                    "is too large.",
                    complexity_evidence(complexity)
                    | {
                        "row_count": request.primary_execution.row_count,
                        "truncated": request.primary_execution.truncated,
                        "max_result_rows": self._settings.confidence_multi_query_max_result_rows,
                    },
                ),
            )

        started = perf_counter()
        prompt = build_independent_prompt(
            request.question,
            request.catalog,
            request.retrieval,
            complexity,
            self._settings,
            self._prompt_engine,
        )
        try:
            alternate_draft = self._sql_generator.generate(prompt)
        except SQLGenerationError as exc:
            return (
                unavailable_signal(
                    "multi_query_generation_unavailable",
                    "Multi-query validation could not generate an independent SQL draft.",
                    complexity_evidence(complexity)
                    | {"generation_error_code": exc.public_code},
                ),
            )
        if deadline_exceeded(started, self._settings):
            return (
                unavailable_signal(
                    "multi_query_timeout",
                    "Multi-query validation exceeded its total time budget after generation.",
                    timeout_evidence(started, self._settings) | complexity_evidence(complexity),
                ),
            )
        if (
            alternate_draft.telemetry.retry_count
            > self._settings.confidence_multi_query_max_retries
        ):
            return (
                unavailable_signal(
                    "multi_query_retry_budget_exceeded",
                    "Multi-query validation exceeded its configured provider retry budget.",
                    complexity_evidence(complexity)
                    | {
                        "retry_count": alternate_draft.telemetry.retry_count,
                        "max_retries": self._settings.confidence_multi_query_max_retries,
                    },
                ),
            )
        if alternate_draft.result.clarification_needed or alternate_draft.result.sql is None:
            return (
                unavailable_signal(
                    "multi_query_generation_incomplete",
                    "The independent SQL generator did not return executable SQL.",
                    complexity_evidence(complexity),
                ),
            )

        try:
            secondary_execution = self._query_executor.execute(
                alternate_draft.result.sql,
                request.catalog,
            )
        except SQLGuardrailValidationError as exc:
            return (
                unavailable_signal(
                    "multi_query_secondary_blocked",
                    "Independent SQL was blocked by the safety pipeline.",
                    complexity_evidence(complexity)
                    | {
                        "finding_codes": [finding.code for finding in exc.result.findings],
                        "secondary_sql_hash": sql_hash(alternate_draft.result.sql),
                    },
                ),
            )
        except QueryPlanInspectionError as exc:
            return (
                unavailable_signal(
                    "multi_query_secondary_plan_unavailable",
                    "Independent SQL could not pass EXPLAIN inspection.",
                    complexity_evidence(complexity)
                    | {"error_code": exc.public_code},
                ),
            )
        except QueryExecutionError as exc:
            return (
                unavailable_signal(
                    "multi_query_secondary_execution_unavailable",
                    "Independent SQL could not be executed safely.",
                    complexity_evidence(complexity)
                    | {"error_code": exc.public_code},
                ),
            )

        if deadline_exceeded(started, self._settings):
            return (
                unavailable_signal(
                    "multi_query_timeout",
                    "Multi-query validation exceeded its total time budget after execution.",
                    timeout_evidence(started, self._settings) | complexity_evidence(complexity),
                ),
            )
        if (
            secondary_execution.execution_duration_ms
            > self._settings.confidence_multi_query_max_execution_ms
        ):
            return (
                unavailable_signal(
                    "multi_query_secondary_execution_timeout",
                    "Independent SQL exceeded the configured execution-time budget.",
                    complexity_evidence(complexity)
                    | {
                        "execution_duration_ms": secondary_execution.execution_duration_ms,
                        "max_execution_ms": self._settings.confidence_multi_query_max_execution_ms,
                    },
                ),
            )

        if same_sql_shape(request.primary_execution.executed_sql, secondary_execution.executed_sql):
            return (
                unavailable_signal(
                    "multi_query_not_independent",
                    "Independent SQL matched the primary SQL shape too closely to add evidence.",
                    complexity_evidence(complexity)
                    | {
                        "primary_sql_hash": sql_hash(request.primary_execution.executed_sql),
                        "secondary_sql_hash": sql_hash(secondary_execution.executed_sql),
                    },
                ),
            )

        comparison = compare_result_sets(
            request.primary_execution,
            secondary_execution,
            self._settings,
        )
        return (
            comparison_signal(
                comparison,
                request,
                secondary_execution,
                alternate_draft,
                complexity,
            ),
        )


def build_independent_prompt(
    question: str,
    catalog: SchemaCatalog,
    retrieval: SchemaRetrievalResult,
    complexity: QueryComplexity,
    settings: Settings,
    prompt_engine: SchemaAwarePromptEngine,
) -> SQLGenerationPrompt:
    base_prompt = prompt_engine.build_prompt(question, catalog, retrieval)
    strategy = alternate_strategy(complexity)
    return SQLGenerationPrompt(
        original_question=question,
        sql_dialect=base_prompt.sql_dialect,
        messages=(
            *base_prompt.messages,
            PromptMessage(
                "user",
                "\n".join(
                    (
                        "Generate one independent alternate SQL approach for validation.",
                        "Use only the retrieved schema context already provided above.",
                        "Do not use the primary SQL, primary result, or model confidence.",
                        "Return the same structured SQL JSON shape.",
                        "The SQL must still be a single read-only SELECT.",
                        f"Independent strategy: {strategy}",
                    )
                ),
            ),
        ),
        selected_few_shot_ids=base_prompt.selected_few_shot_ids,
        context_budget_chars=base_prompt.context_budget_chars,
        context_chars=base_prompt.context_chars,
        truncated=base_prompt.truncated,
    )


def alternate_strategy(complexity: QueryComplexity) -> str:
    if complexity.classification == "grouped_comparison":
        return "stage the grouping in a CTE or subquery, then aggregate from that staged grain"
    if complexity.classification == "aggregate":
        return "use an equivalent aggregate expression with explicit entity grain"
    if complexity.classification == "join_sensitive":
        return "prefer EXISTS or pre-aggregation to avoid one-to-many row multiplication"
    return "use the simplest safe SELECT"


def comparison_signal(
    comparison: ResultComparison,
    request: MultiQueryAgreementRequest,
    secondary_execution: QueryExecutionResult,
    alternate_draft: SQLGenerationDraft,
    complexity: QueryComplexity,
) -> ValidationSignal:
    evidence = comparison.evidence | complexity_evidence(complexity) | {
        "comparison_code": comparison.code,
        "primary_sql_hash": sql_hash(request.primary_execution.executed_sql),
        "secondary_sql_hash": sql_hash(secondary_execution.executed_sql),
        "secondary_provider": alternate_draft.telemetry.provider_name,
        "secondary_model": alternate_draft.telemetry.model_name,
        "secondary_retry_count": alternate_draft.telemetry.retry_count,
    }
    if comparison.outcome == "agreement":
        return ValidationSignal(
            "multi_query_result_agreement",
            "passed",
            1.0,
            "Independent SQL produced an equivalent result set through the safety pipeline.",
            evidence,
        )
    if comparison.outcome == "disagreement":
        return ValidationSignal(
            "multi_query_result_disagreement",
            "failed",
            0.0,
            "Independent SQL produced a materially different result set.",
            evidence,
        )
    return ValidationSignal(
        "multi_query_result_incomparable",
        "warning",
        0.5,
        "Independent SQL ran safely, but its result set could not be compared reliably.",
        evidence,
    )


def same_sql_shape(primary_sql: str, secondary_sql: str) -> bool:
    if not primary_sql or not secondary_sql:
        return False
    return sql_fingerprint(primary_sql) == sql_fingerprint(secondary_sql)


def sql_fingerprint(sql: str) -> str:
    try:
        return sqlglot.parse_one(sql, read=POSTGRES_DIALECT).sql(dialect=POSTGRES_DIALECT)
    except ParseError:
        return re.sub(r"\s+", " ", sql.casefold()).strip()


def deadline_exceeded(started: float, settings: Settings) -> bool:
    return (perf_counter() - started) > settings.confidence_multi_query_timeout_seconds


def timeout_evidence(started: float, settings: Settings) -> dict[str, float]:
    return {
        "elapsed_seconds": round(perf_counter() - started, 3),
        "timeout_seconds": settings.confidence_multi_query_timeout_seconds,
    }


def complexity_evidence(complexity: QueryComplexity) -> dict[str, object]:
    return {
        "complexity_class": complexity.classification,
        "complexity_reasons": complexity.reasons,
        "eligible": complexity.eligible,
    }


def sql_hash(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()[:16]


def unavailable_signal(
    code: str,
    explanation: str,
    evidence: dict[str, object] | None = None,
) -> ValidationSignal:
    return ValidationSignal(code, "unavailable", 0.0, explanation, evidence or {})


def not_applicable_signal(
    code: str,
    explanation: str,
    evidence: dict[str, object] | None = None,
) -> ValidationSignal:
    return ValidationSignal(code, "not_applicable", 0.0, explanation, evidence or {})


def tokenize(text: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", text).casefold().replace("_", " ")
    return set(re.findall(r"[a-z0-9]+", normalized))


AGGREGATE_FUNCTIONS = frozenset({"avg", "count", "max", "min", "sum"})
GROUPING_TERMS = frozenset(
    {
        "by",
        "compare",
        "comparison",
        "daily",
        "month",
        "monthly",
        "per",
        "quarter",
        "region",
        "trend",
        "weekly",
        "year",
    }
)
METRIC_TERMS = frozenset(
    {
        "average",
        "count",
        "gross",
        "maximum",
        "minimum",
        "net",
        "percent",
        "percentage",
        "rate",
        "revenue",
        "sales",
        "sum",
        "total",
    }
)
JOIN_SENSITIVE_TERMS = frozenset(
    {
        "bought",
        "category",
        "customer",
        "customers",
        "orders",
        "payments",
        "products",
        "refunds",
        "shipments",
    }
)
