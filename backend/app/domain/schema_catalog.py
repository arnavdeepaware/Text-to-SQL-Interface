from dataclasses import dataclass

from app.domain.glossary import BusinessGlossary
from app.domain.schema import DatabaseSchema


@dataclass(frozen=True)
class ColumnSample:
    """Safe representative values for a single categorical column."""

    table_identifier: str
    column_name: str
    values: tuple[str, ...]


@dataclass(frozen=True)
class SchemaCatalog:
    """Enriched schema catalog used by API adapters."""

    database_schema: DatabaseSchema
    samples: tuple[ColumnSample, ...]
    glossary: BusinessGlossary
    generated_at_epoch_seconds: float
    cache_expires_at_epoch_seconds: float
    refreshed: bool
