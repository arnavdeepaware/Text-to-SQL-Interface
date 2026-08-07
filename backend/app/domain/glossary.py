from dataclasses import dataclass


@dataclass(frozen=True)
class GlossaryTerm:
    """Business glossary term independent from HTTP response contracts."""

    name: str
    definition: str
    expression: str
    related_tables: tuple[str, ...] = ()
    related_columns: tuple[str, ...] = ()


@dataclass(frozen=True)
class BusinessGlossary:
    """Versioned glossary metadata for schema-aware clients."""

    version: int
    terms: tuple[GlossaryTerm, ...]

