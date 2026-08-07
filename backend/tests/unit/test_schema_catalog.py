from typing import cast
from unittest.mock import Mock

from sqlalchemy import Engine

from app.core.config import Settings
from app.domain.glossary import BusinessGlossary, GlossaryTerm
from app.domain.schema import ColumnSchema, DatabaseSchema, PrimaryKeySchema, TableSchema
from app.domain.schema_catalog import ColumnSample
from app.services.schema_catalog import SchemaCatalogService


class FakeClock:
    def __init__(self, current_time: float) -> None:
        self.current_time = current_time

    def __call__(self) -> float:
        return self.current_time


class FakeIntrospectionService:
    calls = 0

    def __init__(self, engine: Engine, settings: Settings) -> None:
        self._engine = engine
        self._settings = settings

    def introspect(self) -> DatabaseSchema:
        FakeIntrospectionService.calls += 1
        return DatabaseSchema(
            schemas=("commerce",),
            tables=(
                TableSchema(
                    schema_name="commerce",
                    name="orders",
                    columns=(
                        ColumnSchema("status", "TEXT", False),
                    ),
                    primary_key=PrimaryKeySchema(("order_id",), "orders_pkey"),
                ),
            ),
        )


class FakeSampleService:
    calls = 0

    def __init__(self, engine: Engine, settings: Settings) -> None:
        self._engine = engine
        self._settings = settings

    def collect_samples(self, database_schema: DatabaseSchema) -> tuple[ColumnSample, ...]:
        FakeSampleService.calls += 1
        return (
            ColumnSample(
                table_identifier="commerce.orders",
                column_name="status",
                values=("paid",),
            ),
        )


class FakeGlossaryLoader:
    def load(self) -> BusinessGlossary:
        return BusinessGlossary(
            version=1,
            terms=(GlossaryTerm("gross revenue", "Total order value.", "sum(total_cents)"),),
        )


def test_schema_catalog_cache_reuses_entry_until_ttl_or_refresh() -> None:
    FakeIntrospectionService.calls = 0
    FakeSampleService.calls = 0
    clock = FakeClock(100.0)
    service = SchemaCatalogService(
        cast(Engine, Mock(spec=Engine)),
        Settings(environment="test", schema_cache_ttl_seconds=30),
        clock=clock,
        glossary_loader=FakeGlossaryLoader(),
        introspection_factory=FakeIntrospectionService,
        sample_factory=FakeSampleService,
    )

    first = service.get_schema()
    second = service.get_schema()
    clock.current_time = 129.0
    third = service.get_schema()
    refreshed = service.get_schema(refresh=True)
    clock.current_time = 161.0
    expired = service.get_schema()

    assert first is second
    assert second is third
    assert refreshed is not first
    assert refreshed.refreshed is True
    assert expired is not refreshed
    assert FakeIntrospectionService.calls == 3
    assert FakeSampleService.calls == 3

