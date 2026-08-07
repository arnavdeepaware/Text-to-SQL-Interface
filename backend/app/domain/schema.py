from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class ColumnSchema:
    """Database column metadata independent from HTTP response contracts."""

    name: str
    sql_type: str
    nullable: bool
    default: str | None = None


@dataclass(frozen=True)
class PrimaryKeySchema:
    """Primary-key metadata for a table."""

    columns: tuple[str, ...]
    name: str | None = None


@dataclass(frozen=True)
class ForeignKeySchema:
    """Foreign-key relationship metadata with machine and display forms."""

    source_schema: str
    source_table: str
    constrained_columns: tuple[str, ...]
    referred_schema: str
    referred_table: str
    referred_columns: tuple[str, ...]
    name: str | None = None
    options: MappingProxyType[str, Any] = field(
        default_factory=lambda: MappingProxyType({}),
        repr=False,
    )

    @property
    def source_table_identifier(self) -> str:
        return f"{self.source_schema}.{self.source_table}"

    @property
    def referred_table_identifier(self) -> str:
        return f"{self.referred_schema}.{self.referred_table}"

    @property
    def display_path(self) -> str:
        source_columns = ", ".join(self.constrained_columns)
        referred_columns = ", ".join(self.referred_columns)
        return (
            f"{self.source_table_identifier}.{source_columns} -> "
            f"{self.referred_table_identifier}.{referred_columns}"
        )


@dataclass(frozen=True)
class TableSchema:
    """Database table metadata for schema-aware Text-to-SQL behavior."""

    schema_name: str
    name: str
    columns: tuple[ColumnSchema, ...]
    primary_key: PrimaryKeySchema
    foreign_keys: tuple[ForeignKeySchema, ...] = ()

    @property
    def identifier(self) -> str:
        return f"{self.schema_name}.{self.name}"


@dataclass(frozen=True)
class DatabaseSchema:
    """Introspected database schema catalog."""

    schemas: tuple[str, ...]
    tables: tuple[TableSchema, ...]

    def table(self, schema_name: str, table_name: str) -> TableSchema | None:
        for table in self.tables:
            if table.schema_name == schema_name and table.name == table_name:
                return table
        return None

