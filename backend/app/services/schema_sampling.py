import logging
from collections.abc import Iterable

from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.domain.schema import ColumnSchema, DatabaseSchema, TableSchema
from app.domain.schema_catalog import ColumnSample

logger = logging.getLogger(__name__)

SENSITIVE_COLUMN_TOKENS = frozenset(
    {
        "address",
        "email",
        "external",
        "full",
        "identifier",
        "name",
        "number",
        "payment",
        "phone",
        "provider",
        "sku",
        "text",
        "tracking",
    }
)
TEXTUAL_SQL_TYPE_TOKENS = ("CHAR", "TEXT", "VARCHAR")


class SchemaSampleService:
    """Fetch bounded safe categorical samples for introspected columns."""

    def __init__(self, engine: Engine, settings: Settings) -> None:
        self._engine = engine
        self._settings = settings

    def collect_samples(self, database_schema: DatabaseSchema) -> tuple[ColumnSample, ...]:
        if self._settings.schema_sample_limit == 0:
            return ()

        safe_columns = set(self._settings.schema_sample_columns)
        samples: list[ColumnSample] = []

        for table in database_schema.tables:
            for column in table.columns:
                if not self._should_sample(table, column, safe_columns):
                    continue

                values = self._sample_values(table, column)
                if values:
                    samples.append(
                        ColumnSample(
                            table_identifier=table.identifier,
                            column_name=column.name,
                            values=values,
                        )
                    )

        return tuple(samples)

    def _should_sample(
        self,
        table: TableSchema,
        column: ColumnSchema,
        safe_columns: set[str],
    ) -> bool:
        column_identifier = f"{table.identifier}.{column.name}"
        return (
            column_identifier in safe_columns
            and is_textual_sql_type(column.sql_type)
            and not is_sensitive_column_name(column.name)
        )

    def _sample_values(self, table: TableSchema, column: ColumnSchema) -> tuple[str, ...]:
        limit = self._settings.schema_sample_limit
        query_limit = limit + 1
        preparer = self._engine.dialect.identifier_preparer
        schema_name = preparer.quote_schema(table.schema_name)
        table_name = preparer.quote(table.name)
        column_name = preparer.quote(column.name)

        sample_query = text(
            f"""
            SELECT {column_name}::text AS value
            FROM (
                SELECT DISTINCT {column_name}
                FROM {schema_name}.{table_name}
                WHERE {column_name} IS NOT NULL
                  AND length(btrim({column_name}::text)) > 0
                ORDER BY {column_name}
                LIMIT :limit
            ) AS distinct_values
            """
        )

        try:
            with self._engine.connect() as connection:
                connection.execute(
                    text(f"SET LOCAL statement_timeout = {self._settings.schema_sample_timeout_ms}")
                )
                rows = connection.execute(sample_query, {"limit": query_limit}).scalars().all()
        except SQLAlchemyError:
            logger.warning(
                "Schema sample query failed",
                extra={"table": table.identifier, "column": column.name},
            )
            return ()

        values = tuple(str(value) for value in rows)
        if len(values) > limit:
            return ()
        return values


def is_textual_sql_type(sql_type: str) -> bool:
    normalized = sql_type.upper()
    return any(token in normalized for token in TEXTUAL_SQL_TYPE_TOKENS)


def is_sensitive_column_name(column_name: str) -> bool:
    tokens = tokenize_identifier(column_name)
    return any(token in SENSITIVE_COLUMN_TOKENS for token in tokens)


def tokenize_identifier(identifier: str) -> tuple[str, ...]:
    return tuple(token for token in identifier.lower().replace("-", "_").split("_") if token)


def sample_lookup(samples: Iterable[ColumnSample]) -> dict[tuple[str, str], tuple[str, ...]]:
    return {
        (sample.table_identifier, sample.column_name): sample.values
        for sample in samples
    }
