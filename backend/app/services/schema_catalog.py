from collections.abc import Callable
from threading import Lock
from time import time
from typing import Protocol

from sqlalchemy import Engine

from app.core.config import Settings
from app.domain.glossary import BusinessGlossary
from app.domain.schema import DatabaseSchema
from app.domain.schema_catalog import ColumnSample, SchemaCatalog
from app.services.glossary_loader import BusinessGlossaryLoader
from app.services.schema_introspection import SchemaIntrospectionService
from app.services.schema_sampling import SchemaSampleService

Clock = Callable[[], float]


class IntrospectionProvider(Protocol):
    def introspect(self) -> DatabaseSchema: ...


class SampleProvider(Protocol):
    def collect_samples(self, database_schema: DatabaseSchema) -> tuple[ColumnSample, ...]: ...


class GlossaryProvider(Protocol):
    def load(self) -> BusinessGlossary: ...


IntrospectionFactory = Callable[[Engine, Settings], IntrospectionProvider]
SampleFactory = Callable[[Engine, Settings], SampleProvider]


class SchemaCatalogService:
    """Coordinate introspection, sampling, glossary loading, and process cache."""

    def __init__(
        self,
        engine: Engine,
        settings: Settings,
        clock: Clock = time,
        glossary_loader: GlossaryProvider | None = None,
        introspection_factory: IntrospectionFactory = SchemaIntrospectionService,
        sample_factory: SampleFactory = SchemaSampleService,
    ) -> None:
        self._engine = engine
        self._settings = settings
        self._clock = clock
        self._glossary_loader = glossary_loader or BusinessGlossaryLoader()
        self._introspection_factory = introspection_factory
        self._sample_factory = sample_factory
        self._lock = Lock()
        self._cached_catalog: SchemaCatalog | None = None

    def get_schema(self, refresh: bool = False) -> SchemaCatalog:
        now = self._clock()
        with self._lock:
            if not refresh and self._cached_catalog is not None:
                if now < self._cached_catalog.cache_expires_at_epoch_seconds:
                    return self._cached_catalog

            catalog = self._build_catalog(generated_at=now, refreshed=refresh)
            self._cached_catalog = catalog
            return catalog

    def _build_catalog(self, generated_at: float, refreshed: bool) -> SchemaCatalog:
        database_schema = self._introspection_factory(self._engine, self._settings).introspect()
        samples = self._sample_factory(self._engine, self._settings).collect_samples(
            database_schema
        )
        glossary = self._glossary_loader.load()
        return SchemaCatalog(
            database_schema=database_schema,
            samples=samples,
            glossary=glossary,
            generated_at_epoch_seconds=generated_at,
            cache_expires_at_epoch_seconds=generated_at + self._settings.schema_cache_ttl_seconds,
            refreshed=refreshed,
        )
