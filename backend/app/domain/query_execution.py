from dataclasses import dataclass
from typing import Any

from app.domain.sql_guardrails import SQLValidationFinding, SQLValidationMetadata


@dataclass(frozen=True)
class QueryResultColumn:
    """Column metadata for a guarded query result."""

    name: str
    type_code: str | None = None


@dataclass(frozen=True)
class QueryPlanSummary:
    """Public-safe summary extracted from PostgreSQL EXPLAIN JSON."""

    estimated_rows: int
    total_cost: float
    plan_nodes: tuple[str, ...]
    referenced_relations: tuple[str, ...]


@dataclass(frozen=True)
class QueryPlanAudit:
    """Internal-only plan audit data; raw plans must not be returned to clients."""

    summary: QueryPlanSummary
    raw_plan: Any


@dataclass(frozen=True)
class QueryPlanInspection:
    """Result of inspecting a validated SQL statement with EXPLAIN."""

    summary: QueryPlanSummary
    audit: QueryPlanAudit


@dataclass(frozen=True)
class QueryExecutionResult:
    """Typed result of a guarded read-only query execution."""

    columns: tuple[QueryResultColumn, ...]
    rows: tuple[dict[str, Any], ...]
    row_count: int
    execution_duration_ms: int
    truncated: bool
    plan: QueryPlanSummary
    guardrail_findings: tuple[SQLValidationFinding, ...] = ()
    guardrail_metadata: SQLValidationMetadata | None = None
