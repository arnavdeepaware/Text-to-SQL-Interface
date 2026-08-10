from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Literal, Protocol, cast

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import Engine

from app.core.config import Settings
from app.core.exceptions import PublicAPIError
from app.db.lifecycle import get_audit_database_engine
from app.domain.history import (
    FeedbackRating,
    QueryAuditRecord,
    QueryFeedback,
    QueryHistoryPage,
)
from app.repositories.query_history import (
    QueryFeedbackTargetNotFoundError,
    QueryHistoryPersistenceError,
    QueryHistoryRepository,
)
from app.services.query_history import QueryHistoryService, QueryHistoryStore


class QueryHistoryProvider(Protocol):
    def list_records(self, limit: int | None, offset: int) -> QueryHistoryPage: ...

    def add_feedback(
        self,
        request_id: str,
        rating: FeedbackRating,
        comment: str | None,
    ) -> QueryFeedback: ...


QueryHistoryRepositoryFactory = Callable[[Engine], QueryHistoryStore]


class QueryFeedbackRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=200)
    rating: Literal["correct", "incorrect", "unsure"]
    comment: str | None = Field(default=None, max_length=2_000)


class QueryFeedbackResponse(BaseModel):
    id: int
    request_id: str
    rating: Literal["correct", "incorrect", "unsure"]
    comment: str | None
    created_at: datetime


class QueryHistoryRecordResponse(BaseModel):
    id: int
    request_id: str
    normalized_question: str
    generated_sql: str | None
    outcome: Literal["success", "clarification_required", "blocked", "failed"]
    blocked_reasons: list[str]
    execution_metadata: dict[str, object]
    confidence_breakdown: dict[str, object]
    provider_metadata: dict[str, object]
    created_at: datetime
    updated_at: datetime
    feedback: list[QueryFeedbackResponse]


class QueryHistoryResponse(BaseModel):
    records: list[QueryHistoryRecordResponse]
    limit: int
    offset: int
    total: int
    retention_policy: dict[str, int | str]
    privacy_limitations: list[str]


def create_history_router(
    settings: Settings,
    repository_factory: QueryHistoryRepositoryFactory = QueryHistoryRepository,
) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["history"])

    @router.get("/history", response_model=QueryHistoryResponse)
    async def get_history(
        request: Request,
        limit: int | None = None,
        offset: int = 0,
    ) -> QueryHistoryResponse:
        if offset < 0:
            raise PublicAPIError(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "invalid_history_offset",
                "History offset must be greater than or equal to zero.",
            )
        service = get_query_history_service(request, settings, repository_factory)
        try:
            page = service.list_records(limit=limit, offset=offset)
        except QueryHistoryPersistenceError as exc:
            raise PublicAPIError(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "query_history_unavailable",
                "Query history is unavailable.",
            ) from exc
        return history_response(page, settings)

    @router.post(
        "/feedback",
        response_model=QueryFeedbackResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def post_feedback(
        payload: QueryFeedbackRequest,
        request: Request,
    ) -> QueryFeedbackResponse:
        service = get_query_history_service(request, settings, repository_factory)
        try:
            feedback = service.add_feedback(
                request_id=payload.request_id,
                rating=payload.rating,
                comment=payload.comment,
            )
        except QueryFeedbackTargetNotFoundError as exc:
            raise PublicAPIError(
                status.HTTP_404_NOT_FOUND,
                "query_history_record_not_found",
                "Feedback must reference an existing query history record.",
            ) from exc
        except QueryHistoryPersistenceError as exc:
            raise PublicAPIError(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "query_feedback_unavailable",
                "Query feedback could not be stored.",
            ) from exc
        return feedback_response(feedback)

    return router


def get_query_history_service(
    request: Request,
    settings: Settings,
    repository_factory: QueryHistoryRepositoryFactory,
) -> QueryHistoryProvider:
    cached_service = getattr(request.app.state, "query_history_service", None)
    if cached_service is not None:
        return cast(QueryHistoryProvider, cached_service)

    repository = repository_factory(get_audit_database_engine(request.app))
    service = QueryHistoryService(settings, repository)
    request.app.state.query_history_service = service
    return service


def history_response(page: QueryHistoryPage, settings: Settings) -> QueryHistoryResponse:
    return QueryHistoryResponse(
        records=[record_response(record) for record in page.records],
        limit=page.limit,
        offset=page.offset,
        total=page.total,
        retention_policy={
            "status": "placeholder",
            "query_history_retention_days": settings.query_history_retention_days,
            "query_feedback_retention_days": settings.query_feedback_retention_days,
        },
        privacy_limitations=[
            "History is redacted for likely secrets but is not a full data-loss-prevention system.",
            (
                "Raw result rows, raw prompts, credentials, and full provider responses are "
                "not stored."
            ),
        ],
    )


def record_response(record: QueryAuditRecord) -> QueryHistoryRecordResponse:
    return QueryHistoryRecordResponse(
        id=record.id,
        request_id=record.request_id,
        normalized_question=record.normalized_question,
        generated_sql=record.generated_sql,
        outcome=record.outcome,
        blocked_reasons=list(record.blocked_reasons),
        execution_metadata=record.execution_metadata,
        confidence_breakdown=record.confidence_breakdown,
        provider_metadata=record.provider_metadata,
        created_at=record.created_at,
        updated_at=record.updated_at,
        feedback=[feedback_response(item) for item in record.feedback],
    )


def feedback_response(feedback: QueryFeedback) -> QueryFeedbackResponse:
    return QueryFeedbackResponse(
        id=feedback.id,
        request_id=feedback.request_id,
        rating=feedback.rating,
        comment=feedback.comment,
        created_at=feedback.created_at,
    )
