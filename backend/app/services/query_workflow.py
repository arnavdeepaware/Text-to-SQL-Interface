from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from app.core.config import Settings
from app.domain.confidence import ConfidenceSummary, ValidationSignal
from app.domain.query_execution import QueryExecutionResult
from app.domain.schema_catalog import SchemaCatalog
from app.domain.sql_generation import SQLGenerationDraft
from app.providers.sql_generation import SQLGenerationError, SQLGenerator
from app.services.confidence_aggregation import (
    ConfidenceScoringRequest,
    ConfidenceScoringService,
)
from app.services.confidence_signals import (
    DeterministicValidationRequest,
    DeterministicValidationService,
)
from app.services.multi_query_agreement import (
    MultiQueryAgreementRequest,
    MultiQueryAgreementService,
)
from app.services.query_draft import (
    ClarificationRequired,
    QueryDraftResult,
    QueryDraftService,
    normalize_question,
)
from app.services.query_execution import QueryExecutionError, QueryPlanInspectionError
from app.services.semantic_alignment import SemanticAlignmentRequest, SemanticAlignmentService
from app.services.sql_guardrails import SQLGuardrailValidationError

logger = logging.getLogger(__name__)


class SchemaCatalogProvider(Protocol):
    def get_schema(self, refresh: bool = False) -> SchemaCatalog: ...


class QueryExecutor(Protocol):
    def execute(self, sql: str, catalog: SchemaCatalog) -> QueryExecutionResult: ...


class QueryDraftProvider(Protocol):
    def draft(self, question: str, catalog: SchemaCatalog) -> QueryDraftResult: ...


class DeterministicValidator(Protocol):
    def validate(self, request: DeterministicValidationRequest) -> tuple[ValidationSignal, ...]: ...


class SemanticValidator(Protocol):
    def validate(self, request: SemanticAlignmentRequest) -> tuple[ValidationSignal, ...]: ...


class MultiQueryValidator(Protocol):
    def evaluate(self, request: MultiQueryAgreementRequest) -> tuple[ValidationSignal, ...]: ...


class ConfidenceScorer(Protocol):
    def score(self, request: ConfidenceScoringRequest) -> ConfidenceSummary: ...


class QueryWorkflowError(RuntimeError):
    """Stable public-safe error for unexpected workflow state."""

    public_code = "query_workflow_error"
    public_message = "The query workflow failed."


class QueryWorkflowMissingResultError(QueryWorkflowError):
    public_code = "query_execution_missing_result"
    public_message = "Query generation did not produce a result."


class QueryWorkflowMissingSQLError(QueryWorkflowError):
    public_code = "sql_generation_missing_sql"
    public_message = "The SQL provider did not return a SQL draft."


@dataclass(frozen=True)
class QueryWorkflowResult:
    """Outcome of the safe end-to-end query workflow."""

    question: str
    draft: SQLGenerationDraft | None = None
    execution: QueryExecutionResult | None = None
    clarification: ClarificationRequired | None = None
    validation_signals: tuple[ValidationSignal, ...] = ()
    confidence: ConfidenceSummary | None = None


class QueryWorkflowService:
    """Orchestrate the safe POST /v1/query Text-to-SQL workflow."""

    def __init__(
        self,
        settings: Settings,
        catalog_provider: SchemaCatalogProvider,
        sql_generator: SQLGenerator,
        query_executor: QueryExecutor,
        request_id: str,
        draft_service: QueryDraftProvider | None = None,
        deterministic_validator: DeterministicValidator | None = None,
        semantic_validator: SemanticValidator | None = None,
        multi_query_validator: MultiQueryValidator | None = None,
        confidence_scorer: ConfidenceScorer | None = None,
    ) -> None:
        self._settings = settings
        self._catalog_provider = catalog_provider
        self._sql_generator = sql_generator
        self._query_executor = query_executor
        self._request_id = request_id
        self._draft_service = draft_service
        self._deterministic_validator = deterministic_validator or DeterministicValidationService(
            settings
        )
        self._semantic_validator = semantic_validator
        self._multi_query_validator = multi_query_validator
        self._confidence_scorer = confidence_scorer or ConfidenceScoringService(settings)

    def run(self, question: str, refresh_schema: bool = False) -> QueryWorkflowResult:
        log_audit("started", self._request_id)
        try:
            normalized_question = validate_question(question, self._settings)
        except QueryWorkflowValidationError as exc:
            log_audit(
                "invalid_request",
                self._request_id,
                error_code=exc.public_code,
            )
            raise

        catalog = self._catalog_provider.get_schema(refresh=refresh_schema)
        draft_service = self._draft_service or QueryDraftService(
            self._settings,
            self._sql_generator,
        )

        try:
            draft_result = draft_service.draft(normalized_question, catalog)
        except (SQLGenerationError, SQLGuardrailValidationError):
            log_audit("blocked_before_execution", self._request_id)
            raise

        if draft_result.clarification is not None:
            log_audit("clarification_required", self._request_id)
            return QueryWorkflowResult(
                question=normalized_question,
                clarification=draft_result.clarification,
            )

        if draft_result.draft is None:
            log_audit("failed_missing_result", self._request_id)
            raise QueryWorkflowMissingResultError("Query draft missing result")
        if draft_result.draft.result.sql is None:
            log_audit("failed_missing_sql", self._request_id)
            raise QueryWorkflowMissingSQLError("Query draft missing SQL")

        try:
            execution = self._query_executor.execute(draft_result.draft.result.sql, catalog)
        except (SQLGuardrailValidationError, QueryPlanInspectionError, QueryExecutionError):
            log_audit("blocked_or_failed_execution", self._request_id)
            raise

        validation_signals = list(
            self._deterministic_validator.validate(
                DeterministicValidationRequest(
                    question=normalized_question,
                    catalog=catalog,
                    draft=draft_result.draft,
                    execution=execution,
                    retrieval=draft_result.retrieval,
                )
            )
        )
        semantic_validator = self._semantic_validator
        if semantic_validator is None and self._settings.confidence_semantic_enabled:
            semantic_validator = SemanticAlignmentService(self._settings)
        if semantic_validator is not None:
            validation_signals.extend(
                semantic_validator.validate(
                    SemanticAlignmentRequest(
                        question=normalized_question,
                        execution=execution,
                    )
                )
            )

        multi_query_validator = self._multi_query_validator
        if multi_query_validator is None and self._settings.confidence_multi_query_enabled:
            multi_query_validator = MultiQueryAgreementService(
                self._settings,
                self._sql_generator,
                self._query_executor,
            )
        if multi_query_validator is not None:
            validation_signals.extend(
                multi_query_validator.evaluate(
                    MultiQueryAgreementRequest(
                        question=normalized_question,
                        catalog=catalog,
                        retrieval=draft_result.retrieval,
                        primary_draft=draft_result.draft,
                        primary_execution=execution,
                        validation_signals=tuple(validation_signals),
                    )
                )
            )

        validation_signals_tuple = tuple(validation_signals)
        confidence = self._confidence_scorer.score(
            ConfidenceScoringRequest(
                validation_signals=validation_signals_tuple,
                model_confidence=draft_result.draft.result.model_confidence,
                sql_executed=True,
                guardrail_approved=True,
            )
        )
        log_audit(
            "executed",
            self._request_id,
            row_count=execution.row_count,
            truncated=execution.truncated,
            plan_estimated_rows=execution.plan.estimated_rows,
            plan_total_cost=execution.plan.total_cost,
            validation_signal_codes=[signal.code for signal in validation_signals_tuple],
            confidence_status=confidence.status,
            confidence_band=confidence.confidence_band,
            confidence_score=confidence.score,
        )
        return QueryWorkflowResult(
            question=normalized_question,
            draft=draft_result.draft,
            execution=execution,
            validation_signals=validation_signals_tuple,
            confidence=confidence,
        )


def validate_question(question: str, settings: Settings) -> str:
    normalized = normalize_question(question)
    if not normalized:
        raise QueryWorkflowValidationError(
            "empty_question",
            "Question must not be empty.",
            status_code=422,
        )
    if len(normalized) > settings.query_max_question_chars:
        raise QueryWorkflowValidationError(
            "question_too_long",
            f"Question must be at most {settings.query_max_question_chars} characters.",
            status_code=413,
        )
    return normalized


class QueryWorkflowValidationError(QueryWorkflowError):
    def __init__(self, public_code: str, public_message: str, status_code: int) -> None:
        self.public_code = public_code
        self.public_message = public_message
        self.status_code = status_code
        super().__init__(public_code)


def log_audit(event: str, request_id: str, **metadata: object) -> None:
    logger.info(
        "Query workflow audit",
        extra={
            "request_id": request_id,
            "event": event,
            **metadata,
        },
    )
