from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

FeedbackRating = Literal["correct", "incorrect", "unsure"]
QueryOutcome = Literal["success", "clarification_required", "blocked", "failed"]


@dataclass(frozen=True)
class QueryAuditRecordCreate:
    request_id: str
    normalized_question: str
    outcome: QueryOutcome
    generated_sql: str | None = None
    blocked_reasons: tuple[str, ...] = ()
    execution_metadata: dict[str, Any] = field(default_factory=dict)
    confidence_breakdown: dict[str, Any] = field(default_factory=dict)
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class QueryFeedbackCreate:
    request_id: str
    rating: FeedbackRating
    comment: str | None = None


@dataclass(frozen=True)
class QueryFeedback:
    id: int
    request_id: str
    rating: FeedbackRating
    comment: str | None
    created_at: datetime


@dataclass(frozen=True)
class QueryAuditRecord:
    id: int
    request_id: str
    normalized_question: str
    generated_sql: str | None
    outcome: QueryOutcome
    blocked_reasons: tuple[str, ...]
    execution_metadata: dict[str, Any]
    confidence_breakdown: dict[str, Any]
    provider_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    feedback: tuple[QueryFeedback, ...] = ()


@dataclass(frozen=True)
class QueryHistoryPage:
    records: tuple[QueryAuditRecord, ...]
    limit: int
    offset: int
    total: int
