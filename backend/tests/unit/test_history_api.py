from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from unittest.mock import Mock

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Engine

from app.core.config import Settings
from app.domain.history import (
    QueryAuditRecord,
    QueryAuditRecordCreate,
    QueryFeedback,
    QueryFeedbackCreate,
    QueryHistoryPage,
)
from app.main import create_app
from app.repositories.query_history import QueryFeedbackTargetNotFoundError


async def test_history_endpoint_returns_records_feedback_and_retention_notice() -> None:
    repository = InMemoryHistoryRepository()
    repository.create_or_update_record(
        QueryAuditRecordCreate(
            request_id="req-history",
            normalized_question="Show orders",
            generated_sql="SELECT order_id FROM commerce.orders LIMIT 1",
            outcome="success",
            execution_metadata={"row_count": 1},
            confidence_breakdown={"status": "passed", "score": 0.91},
            provider_metadata={"provider_name": "fake"},
        )
    )
    repository.add_feedback(
        QueryFeedbackCreate(
            request_id="req-history",
            rating="correct",
            comment="Looks good",
        )
    )
    app = history_app(repository)

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/v1/history?limit=10&offset=0")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["records"][0]["request_id"] == "req-history"
    assert payload["records"][0]["feedback"][0]["rating"] == "correct"
    assert payload["retention_policy"]["status"] == "placeholder"
    assert payload["privacy_limitations"]


async def test_feedback_endpoint_redacts_comment_and_links_to_history() -> None:
    repository = InMemoryHistoryRepository()
    repository.create_or_update_record(
        QueryAuditRecordCreate(
            request_id="req-feedback",
            normalized_question="Show orders",
            outcome="success",
        )
    )
    app = history_app(repository)

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            feedback_response = await client.post(
                "/v1/feedback",
                json={
                    "request_id": "req-feedback",
                    "rating": "incorrect",
                    "comment": "password=hunter2hunter2",
                },
            )
            history_response = await client.get("/v1/history")

    assert feedback_response.status_code == 201
    assert feedback_response.json()["comment"] == "password=[REDACTED]"
    feedback = history_response.json()["records"][0]["feedback"][0]
    assert feedback["rating"] == "incorrect"
    assert feedback["comment"] == "password=[REDACTED]"


async def test_feedback_endpoint_rejects_unknown_request_id() -> None:
    app = history_app(InMemoryHistoryRepository())

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/v1/feedback",
                json={"request_id": "missing", "rating": "unsure"},
            )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "query_history_record_not_found"


def history_app(repository: InMemoryHistoryRepository) -> FastAPI:
    fake_engine = Mock(spec=Engine)
    return create_app(
        settings=Settings(environment="test"),
        engine_factory=lambda settings: cast(Engine, fake_engine),
        query_history_repository_factory=lambda engine: repository,
    )


class InMemoryHistoryRepository:
    def __init__(self) -> None:
        self.records: dict[str, QueryAuditRecordCreate] = {}
        self.feedback: list[QueryFeedback] = []

    def ensure_schema(self) -> None:
        return None

    def create_or_update_record(self, record: QueryAuditRecordCreate) -> None:
        self.records[record.request_id] = record

    def add_feedback(self, feedback: QueryFeedbackCreate) -> QueryFeedback:
        if feedback.request_id not in self.records:
            raise QueryFeedbackTargetNotFoundError("missing")
        item = QueryFeedback(
            id=len(self.feedback) + 1,
            request_id=feedback.request_id,
            rating=feedback.rating,
            comment=feedback.comment,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        self.feedback.append(item)
        return item

    def list_records(self, limit: int, offset: int) -> QueryHistoryPage:
        records = list(self.records.values())[offset : offset + limit]
        return QueryHistoryPage(
            records=tuple(
                QueryAuditRecord(
                    id=index + 1,
                    request_id=record.request_id,
                    normalized_question=record.normalized_question,
                    generated_sql=record.generated_sql,
                    outcome=record.outcome,
                    blocked_reasons=record.blocked_reasons,
                    execution_metadata=record.execution_metadata,
                    confidence_breakdown=record.confidence_breakdown,
                    provider_metadata=record.provider_metadata,
                    created_at=datetime(2026, 1, 1, tzinfo=UTC),
                    updated_at=datetime(2026, 1, 1, tzinfo=UTC),
                    feedback=tuple(
                        item
                        for item in self.feedback
                        if item.request_id == record.request_id
                    ),
                )
                for index, record in enumerate(records)
            ),
            limit=limit,
            offset=offset,
            total=len(self.records),
        )
