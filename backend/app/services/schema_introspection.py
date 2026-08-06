from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Any, Protocol, cast

from sqlalchemy import Engine, inspect

from app.core.config import Settings
from app.domain.schema import (
    ColumnSchema,
    DatabaseSchema,
    ForeignKeySchema,
    PrimaryKeySchema,
    TableSchema,
)

POSTGRESQL_INTERNAL_SCHEMAS = frozenset({"information_schema", "pg_catalog"})
PROJECT_AUDIT_TABLE_NAMES = frozenset({"audit_log", "audit_logs"})
PROJECT_AUDIT_TABLE_PREFIXES = ("audit_",)
PROJECT_AUDIT_TABLE_SUFFIXES = ("_audit", "_audits", "_audit_log", "_audit_logs")


class SchemaInspector(Protocol):
    def get_schema_names(self) -> list[str]: ...

    def get_table_names(self, schema: str | None = None) -> list[str]: ...

    def get_columns(self, table_name: str, schema: str | None = None) -> list[dict[str, Any]]: ...

    def get_pk_constraint(
        self,
        table_name: str,
        schema: str | None = None,
    ) -> dict[str, Any]: ...

    def get_foreign_keys(
        self,
        table_name: str,
        schema: str | None = None,
    ) -> list[dict[str, Any]]: ...


class SchemaIntrospectionService:
    """Build typed schema metadata from SQLAlchemy Inspector output."""

    def __init__(
        self,
        engine: Engine,
        settings: Settings,
        inspector: SchemaInspector | None = None,
    ) -> None:
        self._engine = engine
        self._settings = settings
        self._inspector = inspector

    def introspect(self) -> DatabaseSchema:
        inspector = self._inspector or cast(SchemaInspector, inspect(self._engine))
        schema_names = self._included_schema_names(inspector)
        tables: list[TableSchema] = []

        for schema_name in schema_names:
            for table_name in self._included_table_names(inspector, schema_name):
                tables.append(self._introspect_table(inspector, schema_name, table_name))

        return DatabaseSchema(schemas=tuple(schema_names), tables=tuple(tables))

    def _included_schema_names(self, inspector: SchemaInspector) -> list[str]:
        allowed_schemas = set(self._settings.schema_introspection_schemas)
        available_schemas = inspector.get_schema_names()
        return sorted(
            schema_name
            for schema_name in available_schemas
            if schema_name in allowed_schemas and not is_postgresql_internal_schema(schema_name)
        )

    def _included_table_names(self, inspector: SchemaInspector, schema_name: str) -> list[str]:
        return sorted(
            table_name
            for table_name in inspector.get_table_names(schema=schema_name)
            if not is_project_audit_table(table_name)
        )

    def _introspect_table(
        self,
        inspector: SchemaInspector,
        schema_name: str,
        table_name: str,
    ) -> TableSchema:
        columns = tuple(
            self._column_schema(column)
            for column in inspector.get_columns(table_name, schema=schema_name)
        )
        primary_key = self._primary_key_schema(
            inspector.get_pk_constraint(table_name, schema=schema_name)
        )
        foreign_keys = tuple(
            self._foreign_key_schema(schema_name, table_name, foreign_key)
            for foreign_key in sorted(
                inspector.get_foreign_keys(table_name, schema=schema_name),
                key=foreign_key_sort_key,
            )
        )
        return TableSchema(
            schema_name=schema_name,
            name=table_name,
            columns=columns,
            primary_key=primary_key,
            foreign_keys=foreign_keys,
        )

    def _column_schema(self, column: Mapping[str, Any]) -> ColumnSchema:
        return ColumnSchema(
            name=str(column["name"]),
            sql_type=str(column["type"]),
            nullable=bool(column["nullable"]),
            default=stringify_optional(column.get("default")),
        )

    def _primary_key_schema(self, primary_key: Mapping[str, Any]) -> PrimaryKeySchema:
        constrained_columns = primary_key.get("constrained_columns") or ()
        return PrimaryKeySchema(
            columns=tuple(str(column) for column in constrained_columns),
            name=stringify_optional(primary_key.get("name")),
        )

    def _foreign_key_schema(
        self,
        source_schema: str,
        source_table: str,
        foreign_key: Mapping[str, Any],
    ) -> ForeignKeySchema:
        referred_schema = foreign_key.get("referred_schema") or source_schema
        options = foreign_key.get("options") or {}
        return ForeignKeySchema(
            source_schema=source_schema,
            source_table=source_table,
            constrained_columns=string_tuple(foreign_key.get("constrained_columns") or ()),
            referred_schema=str(referred_schema),
            referred_table=str(foreign_key["referred_table"]),
            referred_columns=string_tuple(foreign_key.get("referred_columns") or ()),
            name=stringify_optional(foreign_key.get("name")),
            options=MappingProxyType(dict(options)),
        )


def is_postgresql_internal_schema(schema_name: str) -> bool:
    return schema_name in POSTGRESQL_INTERNAL_SCHEMAS or schema_name.startswith("pg_")


def is_project_audit_table(table_name: str) -> bool:
    return (
        table_name in PROJECT_AUDIT_TABLE_NAMES
        or table_name.startswith(PROJECT_AUDIT_TABLE_PREFIXES)
        or table_name.endswith(PROJECT_AUDIT_TABLE_SUFFIXES)
    )


def stringify_optional(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def string_tuple(values: Iterable[object]) -> tuple[str, ...]:
    return tuple(str(value) for value in values)


def foreign_key_sort_key(
    foreign_key: Mapping[str, Any],
) -> tuple[tuple[str, ...], str, tuple[str, ...], str]:
    constrained_columns = string_tuple(foreign_key.get("constrained_columns") or ())
    referred_columns = string_tuple(foreign_key.get("referred_columns") or ())
    return (
        constrained_columns,
        str(foreign_key.get("referred_table") or ""),
        referred_columns,
        str(foreign_key.get("name") or ""),
    )
