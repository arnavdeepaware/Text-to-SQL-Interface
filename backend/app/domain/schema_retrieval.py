from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.domain.schema import ForeignKeySchema

RetrievalStrategy = Literal["lexical", "embedding", "embedding_fallback"]


@dataclass(frozen=True)
class RetrievalReason:
    """Inspectable explanation for a selected schema object score."""

    source: str
    detail: str
    score: float


@dataclass(frozen=True)
class RankedColumn:
    """Column selected for a natural-language question."""

    table_identifier: str
    column_name: str
    score: float
    reasons: tuple[RetrievalReason, ...]
    selected: bool

    @property
    def identifier(self) -> str:
        return f"{self.table_identifier}.{self.column_name}"


@dataclass(frozen=True)
class RankedTable:
    """Table selected or considered for a natural-language question."""

    identifier: str
    schema_name: str
    table_name: str
    score: float
    reasons: tuple[RetrievalReason, ...]
    selected: bool
    bridge: bool = False


@dataclass(frozen=True)
class RelationshipPathStep:
    """A single foreign-key hop preserved with traversal direction."""

    foreign_key: ForeignKeySchema
    from_table_identifier: str
    to_table_identifier: str

    @property
    def display_path(self) -> str:
        return self.foreign_key.display_path


@dataclass(frozen=True)
class RelationshipPath:
    """Ordered relationship path connecting selected tables."""

    table_identifiers: tuple[str, ...]
    steps: tuple[RelationshipPathStep, ...]

    @property
    def display_path(self) -> str:
        return " | ".join(step.display_path for step in self.steps)


@dataclass(frozen=True)
class SchemaRetrievalResult:
    """Provider-neutral retrieval output for SQL generation and confidence scoring."""

    question: str
    strategy: RetrievalStrategy
    ranked_tables: tuple[RankedTable, ...]
    ranked_columns: tuple[RankedColumn, ...]
    relationship_paths: tuple[RelationshipPath, ...]
    glossary_terms: tuple[str, ...]
    fallback_reason: str | None = None

    @property
    def selected_tables(self) -> tuple[RankedTable, ...]:
        return tuple(table for table in self.ranked_tables if table.selected)

    @property
    def selected_columns(self) -> tuple[RankedColumn, ...]:
        return tuple(column for column in self.ranked_columns if column.selected)
