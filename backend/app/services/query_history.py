from __future__ import annotations

import logging
from typing import Protocol, cast

from app.core.config import Settings
from app.core.redaction import redact_object, redact_text
from app.domain.confidence import ConfidenceSummary
from app.domain.history import (
    FeedbackRating,
    QueryAuditRecordCreate,
    QueryFeedback,
    QueryFeedbackCreate,
    QueryHistoryPage,
    QueryOutcome,
)
from app.domain.query_execution import QueryExecutionResult
from app.domain.sql_generation import SQLGenerationDraft
from app.repositories.query_history import (
    QueryFeedbackTargetNotFoundError,
    QueryHistoryPersistenceError,
    QueryHistoryRepository,
)

logger = logging.getLogger(__name__)


class QueryHistoryStore(Protocol):
    def ensure_schema(self) -> None: ...

    def create_or_update_record(self, record: QueryAuditRecordCreate) -> None: ...

    def add_feedback(self, feedback: QueryFeedbackCreate) -> QueryFeedback: ...

    def list_records(self, limit: int, offset: int) -> QueryHistoryPage: ...


class QueryHistoryService:
    """Redact and persist public-safe query history and feedback."""

    def __init__(self, settings: Settings, repository: QueryHistoryStore) -> None:
        self._settings = settings
        self._repository = repository

    def ensure_storage(self) -> None:
        if not self._settings.query_history_enabled:
            return
        self._repository.ensure_schema()

    def record_query(
        self,
        request_id: str,
        normalized_question: str,
        outcome: QueryOutcome,
        draft: SQLGenerationDraft | None = None,
        execution: QueryExecutionResult | None = None,
        confidence: ConfidenceSummary | None = None,
        blocked_reasons: tuple[str, ...] = (),
        generated_sql: str | None = None,
    ) -> None:
        if not self._settings.query_history_enabled:
            return
        sql_to_store = generated_sql
        if draft is not None and draft.result.sql is not None:
            sql_to_store = draft.result.sql
        record = QueryAuditRecordCreate(
            request_id=request_id,
            normalized_question=redact_text(normalized_question).value,
            generated_sql=redact_text(sql_to_store).value if sql_to_store is not None else None,
            outcome=outcome,
            blocked_reasons=blocked_reasons,
            execution_metadata=execution_metadata(execution),
            confidence_breakdown=confidence_metadata(confidence),
            provider_metadata=provider_metadata(draft),
        )
        self._repository.create_or_update_record(record)

    def try_record_query(self, **kwargs: object) -> None:
        try:
            self.record_query(**kwargs)  # type: ignore[arg-type]
        except QueryHistoryPersistenceError:
            logger.warning(
                "Query history persistence failed",
                extra={"request_id": kwargs.get("request_id")},
                exc_info=True,
            )

    def add_feedback(
        self,
        request_id: str,
        rating: FeedbackRating,
        comment: str | None,
    ) -> QueryFeedback:
        clean_comment = None
        if comment is not None:
            bounded_comment = comment.strip()[: self._settings.query_feedback_comment_max_chars]
            clean_comment = redact_text(bounded_comment).value if bounded_comment else None
        return self._repository.add_feedback(
            QueryFeedbackCreate(
                request_id=request_id,
                rating=rating,
                comment=clean_comment,
            )
        )

    def list_records(self, limit: int | None, offset: int) -> QueryHistoryPage:
        bounded_limit = min(
            limit or self._settings.query_history_default_limit,
            self._settings.query_history_max_limit,
        )
        return self._repository.list_records(limit=bounded_limit, offset=offset)


def execution_metadata(execution: QueryExecutionResult | None) -> dict[str, object]:
    if execution is None:
        return {}
    return cast(
        dict[str, object],
        redact_object(
            {
                "row_count": execution.row_count,
                "execution_duration_ms": execution.execution_duration_ms,
                "truncated": execution.truncated,
                "plan": {
                    "estimated_rows": execution.plan.estimated_rows,
                    "total_cost": execution.plan.total_cost,
                    "plan_nodes": list(execution.plan.plan_nodes),
                    "referenced_relations": list(execution.plan.referenced_relations),
                },
                "guardrail_findings": [
                    {
                        "code": finding.code,
                        "rule_name": finding.rule_name,
                        "severity": finding.severity,
                    }
                    for finding in execution.guardrail_findings
                ],
            }
        ),
    )


def confidence_metadata(confidence: ConfidenceSummary | None) -> dict[str, object]:
    if confidence is None:
        return {}
    return cast(
        dict[str, object],
        redact_object(
            {
                "status": confidence.status,
                "score": confidence.score,
                "confidence_band": confidence.confidence_band,
                "warnings": list(confidence.warnings),
                "rationale": confidence.rationale,
                "components": [
                    {
                        "name": component.name,
                        "status": component.status,
                        "score": component.score,
                        "weight": component.weight,
                        "contribution": component.contribution,
                        "signal_codes": list(component.signal_codes),
                        "evidence": component.evidence,
                    }
                    for component in confidence.components
                ],
                "signals": [
                    {
                        "code": signal.code,
                        "status": signal.status,
                        "score": signal.score,
                        "evidence": signal.evidence,
                    }
                    for signal in confidence.signals
                ],
            }
        ),
    )


def provider_metadata(draft: SQLGenerationDraft | None) -> dict[str, object]:
    if draft is None:
        return {}
    result = draft.result
    telemetry = draft.telemetry
    return cast(
        dict[str, object],
        redact_object(
            {
                "provider_name": telemetry.provider_name,
                "model_name": telemetry.model_name,
                "provider_latency_ms": telemetry.provider_latency_ms,
                "input_tokens": telemetry.input_tokens,
                "output_tokens": telemetry.output_tokens,
                "total_tokens": telemetry.total_tokens,
                "retry_count": telemetry.retry_count,
                "model_confidence": result.model_confidence,
                "tables_used": result.tables_used,
                "columns_used": result.columns_used,
                "assumptions": result.assumptions,
            }
        ),
    )


__all__ = [
    "QueryFeedbackTargetNotFoundError",
    "QueryHistoryPersistenceError",
    "QueryHistoryRepository",
    "QueryHistoryService",
    "QueryHistoryStore",
]
