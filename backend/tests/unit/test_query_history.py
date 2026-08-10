from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.core.config import Settings
from app.domain.history import (
    QueryAuditRecord,
    QueryAuditRecordCreate,
    QueryFeedback,
    QueryFeedbackCreate,
    QueryHistoryPage,
)
from app.repositories.query_history import QueryHistoryPersistenceError
from app.services.query_history import QueryHistoryService


def test_query_history_service_redacts_questions_sql_and_feedback() -> None:
    repository = InMemoryHistoryRepository()
    service = QueryHistoryService(Settings(environment="test"), repository)

    service.record_query(
        request_id="req-secret",
        normalized_question="Show orders for api_key=supersecretvalue123",
        outcome="success",
    )
    feedback = service.add_feedback(
        request_id="req-secret",
        rating="incorrect",
        comment="password=hunter2hunter2",
    )

    record = repository.records["req-secret"]
    assert "supersecretvalue123" not in record.normalized_question
    assert "[REDACTED]" in record.normalized_question
    assert feedback.comment == "password=[REDACTED]"


def test_query_history_service_bounds_page_size() -> None:
    repository = InMemoryHistoryRepository()
    service = QueryHistoryService(
        Settings(
            environment="test",
            query_history_default_limit=2,
            query_history_max_limit=3,
        ),
        repository,
    )

    page = service.list_records(limit=10, offset=0)

    assert page.limit == 3


def test_try_record_query_swallows_persistence_error(caplog: pytest.LogCaptureFixture) -> None:
    service = QueryHistoryService(Settings(environment="test"), FailingHistoryRepository())

    service.try_record_query(
        request_id="req-fail",
        normalized_question="Show orders",
        outcome="blocked",
        blocked_reasons=("sql_validation_failed",),
    )

    assert "Query history persistence failed" in caplog.text

class InMemoryHistoryRepository:
    def __init__(self) -> None:
        self.records: dict[str, QueryAuditRecordCreate] = {}
        self.feedback: list[QueryFeedback] = []
        self.ensured = False

    def ensure_schema(self) -> None:
        self.ensured = True

    def create_or_update_record(self, record: QueryAuditRecordCreate) -> None:
        self.records[record.request_id] = record

    def add_feedback(self, feedback: QueryFeedbackCreate) -> QueryFeedback:
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
        records = tuple(
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
                    item for item in self.feedback if item.request_id == record.request_id
                ),
            )
            for index, record in enumerate(list(self.records.values())[offset : offset + limit])
        )
        return QueryHistoryPage(
            records=records,
            limit=limit,
            offset=offset,
            total=len(self.records),
        )


class FailingHistoryRepository(InMemoryHistoryRepository):
    def create_or_update_record(self, record: QueryAuditRecordCreate) -> None:
        raise QueryHistoryPersistenceError("boom")
