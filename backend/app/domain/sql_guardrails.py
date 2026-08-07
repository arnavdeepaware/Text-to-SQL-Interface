from dataclasses import dataclass
from typing import Literal

SQLValidationSeverity = Literal["error", "warning"]
SQLStatementType = Literal["select", "insert", "update", "delete", "ddl", "command", "unknown"]
SQLReferenceSource = Literal["table", "cte", "subquery", "unknown"]


@dataclass(frozen=True)
class SQLValidationFinding:
    """Machine-readable SQL validation finding with public-safe explanation."""

    code: str
    message: str
    severity: SQLValidationSeverity = "error"


@dataclass(frozen=True)
class ReferencedTable:
    """Table-like source referenced by a parsed SQL statement."""

    name: str
    schema_name: str | None = None
    alias: str | None = None
    source: SQLReferenceSource = "table"

    @property
    def identifier(self) -> str:
        if self.schema_name is None:
            return self.name
        return f"{self.schema_name}.{self.name}"


@dataclass(frozen=True)
class ReferencedColumn:
    """Column reference resolved from SQL scope analysis."""

    name: str
    source_name: str | None = None
    table_identifier: str | None = None
    source: SQLReferenceSource = "unknown"

    @property
    def identifier(self) -> str:
        if self.table_identifier is not None:
            return f"{self.table_identifier}.{self.name}"
        if self.source_name is not None:
            return f"{self.source_name}.{self.name}"
        return self.name


@dataclass(frozen=True)
class SQLValidationMetadata:
    """Structured facts extracted from a parsed SQL statement."""

    statement_type: SQLStatementType
    referenced_tables: tuple[ReferencedTable, ...] = ()
    referenced_columns: tuple[ReferencedColumn, ...] = ()
    aliases: tuple[str, ...] = ()
    functions: tuple[str, ...] = ()
    ctes: tuple[str, ...] = ()
    subquery_depth: int = 0


@dataclass(frozen=True)
class SQLValidationResult:
    """Fail-closed generated SQL validation result."""

    sql: str
    valid: bool
    metadata: SQLValidationMetadata
    findings: tuple[SQLValidationFinding, ...] = ()
