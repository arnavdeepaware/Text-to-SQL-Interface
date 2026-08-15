from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from typing import Any, cast

from sqlalchemy import JSON, Engine, bindparam, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.domain.history import (
    FeedbackRating,
    QueryAuditRecord,
    QueryAuditRecordCreate,
    QueryFeedback,
    QueryFeedbackCreate,
    QueryHistoryPage,
    QueryOutcome,
)


class QueryHistoryPersistenceError(RuntimeError):
    """Raised when query history cannot be persisted or read."""


class QueryFeedbackTargetNotFoundError(QueryHistoryPersistenceError):
    """Raised when feedback references an unknown request ID."""


class QueryHistoryRepository:
    """PostgreSQL-backed query history repository."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def ensure_schema(self) -> None:
        try:
            with self._engine.connect() as connection:
                table = connection.execute(
                    text("SELECT to_regclass('text_to_sql_audit.query_audit_records')")
                ).scalar_one()
                if table is None:
                    raise QueryHistoryPersistenceError("query history schema is unavailable")
        except SQLAlchemyError as exc:
            raise QueryHistoryPersistenceError("query history schema setup failed") from exc

    def create_or_update_record(self, record: QueryAuditRecordCreate) -> None:
        statement = text(
            """
            INSERT INTO text_to_sql_audit.query_audit_records (
                request_id,
                normalized_question,
                generated_sql,
                outcome,
                blocked_reasons,
                execution_metadata,
                confidence_breakdown,
                provider_metadata
            )
            VALUES (
                :request_id,
                :normalized_question,
                :generated_sql,
                :outcome,
                :blocked_reasons,
                :execution_metadata,
                :confidence_breakdown,
                :provider_metadata
            )
            ON CONFLICT (request_id) DO UPDATE SET
                normalized_question = EXCLUDED.normalized_question,
                generated_sql = EXCLUDED.generated_sql,
                outcome = EXCLUDED.outcome,
                blocked_reasons = EXCLUDED.blocked_reasons,
                execution_metadata = EXCLUDED.execution_metadata,
                confidence_breakdown = EXCLUDED.confidence_breakdown,
                provider_metadata = EXCLUDED.provider_metadata,
                updated_at = now()
            """
        ).bindparams(
            bindparam("blocked_reasons", type_=JSON),
            bindparam("execution_metadata", type_=JSON),
            bindparam("confidence_breakdown", type_=JSON),
            bindparam("provider_metadata", type_=JSON),
        )
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    statement,
                    {
                        "request_id": record.request_id,
                        "normalized_question": record.normalized_question,
                        "generated_sql": record.generated_sql,
                        "outcome": record.outcome,
                        "blocked_reasons": list(record.blocked_reasons),
                        "execution_metadata": record.execution_metadata,
                        "confidence_breakdown": record.confidence_breakdown,
                        "provider_metadata": record.provider_metadata,
                    },
                )
        except SQLAlchemyError as exc:
            raise QueryHistoryPersistenceError("query history insert failed") from exc

    def add_feedback(self, feedback: QueryFeedbackCreate) -> QueryFeedback:
        statement = text(
            """
            INSERT INTO text_to_sql_audit.query_feedback (request_id, rating, comment)
            VALUES (:request_id, :rating, :comment)
            RETURNING id, request_id, rating, comment, created_at
            """
        )
        try:
            with self._engine.begin() as connection:
                row = connection.execute(
                    statement,
                    {
                        "request_id": feedback.request_id,
                        "rating": feedback.rating,
                        "comment": feedback.comment,
                    },
                ).mappings().one()
        except IntegrityError as exc:
            raise QueryFeedbackTargetNotFoundError("feedback target query not found") from exc
        except SQLAlchemyError as exc:
            raise QueryHistoryPersistenceError("feedback insert failed") from exc

        return feedback_from_mapping(row)

    def list_records(self, limit: int, offset: int) -> QueryHistoryPage:
        try:
            with self._engine.connect() as connection:
                total = cast(
                    int,
                    connection.execute(
                        text("SELECT count(*) FROM text_to_sql_audit.query_audit_records")
                    ).scalar_one(),
                )
                rows = tuple(
                    connection.execute(
                        text(
                            """
                            SELECT
                                id,
                                request_id,
                                normalized_question,
                                generated_sql,
                                outcome,
                                blocked_reasons,
                                execution_metadata,
                                confidence_breakdown,
                                provider_metadata,
                                created_at,
                                updated_at
                            FROM text_to_sql_audit.query_audit_records
                            ORDER BY created_at DESC, id DESC
                            LIMIT :limit OFFSET :offset
                            """
                        ),
                        {"limit": limit, "offset": offset},
                    )
                    .mappings()
                    .all()
                )
                request_ids = tuple(str(row["request_id"]) for row in rows)
                feedback = feedback_by_request_id(
                    connection.execute(
                        text(
                            """
                            SELECT id, request_id, rating, comment, created_at
                            FROM text_to_sql_audit.query_feedback
                            WHERE request_id IN :request_ids
                            ORDER BY created_at ASC, id ASC
                            """
                        ).bindparams(bindparam("request_ids", expanding=True)),
                        {"request_ids": list(request_ids)},
                    )
                    .mappings()
                    .all()
                    if request_ids
                    else ()
                )
        except SQLAlchemyError as exc:
            raise QueryHistoryPersistenceError("query history read failed") from exc

        return QueryHistoryPage(
            records=tuple(record_from_mapping(row, feedback) for row in rows),
            limit=limit,
            offset=offset,
            total=total,
        )


class NoopQueryHistoryRepository:
    """No-op history store for isolated unit tests that inject mock engines."""

    def ensure_schema(self) -> None:
        return None

    def create_or_update_record(self, record: QueryAuditRecordCreate) -> None:
        return None

    def add_feedback(self, feedback: QueryFeedbackCreate) -> QueryFeedback:
        raise QueryFeedbackTargetNotFoundError("query history is not persisted")

    def list_records(self, limit: int, offset: int) -> QueryHistoryPage:
        return QueryHistoryPage(records=(), limit=limit, offset=offset, total=0)


def feedback_by_request_id(rows: Iterable[Any]) -> dict[str, tuple[QueryFeedback, ...]]:
    grouped: dict[str, list[QueryFeedback]] = defaultdict(list)
    for row in rows:
        item = feedback_from_mapping(row)
        grouped[item.request_id].append(item)
    return {request_id: tuple(items) for request_id, items in grouped.items()}


def feedback_from_mapping(row: Any) -> QueryFeedback:
    return QueryFeedback(
        id=int(row["id"]),
        request_id=str(row["request_id"]),
        rating=cast(FeedbackRating, row["rating"]),
        comment=cast(str | None, row["comment"]),
        created_at=cast(datetime, row["created_at"]),
    )


def record_from_mapping(
    row: Any,
    feedback: dict[str, tuple[QueryFeedback, ...]],
) -> QueryAuditRecord:
    request_id = str(row["request_id"])
    return QueryAuditRecord(
        id=int(row["id"]),
        request_id=request_id,
        normalized_question=str(row["normalized_question"]),
        generated_sql=cast(str | None, row["generated_sql"]),
        outcome=cast(QueryOutcome, row["outcome"]),
        blocked_reasons=tuple(cast(list[str], row["blocked_reasons"] or [])),
        execution_metadata=cast(dict[str, Any], row["execution_metadata"] or {}),
        confidence_breakdown=cast(dict[str, Any], row["confidence_breakdown"] or {}),
        provider_metadata=cast(dict[str, Any], row["provider_metadata"] or {}),
        created_at=cast(datetime, row["created_at"]),
        updated_at=cast(datetime, row["updated_at"]),
        feedback=feedback.get(request_id, ()),
    )
