from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol, cast

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import Engine

from app.core.config import Settings
from app.db.lifecycle import get_database_engine
from app.domain.glossary import GlossaryTerm
from app.domain.schema import ColumnSchema, ForeignKeySchema, TableSchema
from app.domain.schema_catalog import SchemaCatalog
from app.services.schema_catalog import SchemaCatalogService
from app.services.schema_sampling import sample_lookup


class SchemaCatalogProvider(Protocol):
    def get_schema(self, refresh: bool = False) -> SchemaCatalog: ...


SchemaCatalogFactory = Callable[[Engine, Settings], SchemaCatalogProvider]


class ColumnSchemaResponse(BaseModel):
    name: str
    sql_type: str
    nullable: bool
    default: str | None
    sample_values: list[str]


class PrimaryKeySchemaResponse(BaseModel):
    columns: list[str]
    name: str | None


class ForeignKeySchemaResponse(BaseModel):
    name: str | None
    source_schema: str
    source_table: str
    source_columns: list[str]
    referred_schema: str
    referred_table: str
    referred_columns: list[str]
    display_path: str


class TableSchemaResponse(BaseModel):
    schema_name: str
    name: str
    identifier: str
    columns: list[ColumnSchemaResponse]
    primary_key: PrimaryKeySchemaResponse
    foreign_keys: list[ForeignKeySchemaResponse]


class GlossaryTermResponse(BaseModel):
    name: str
    definition: str
    expression: str
    related_tables: list[str]
    related_columns: list[str]


class BusinessGlossaryResponse(BaseModel):
    version: int
    terms: list[GlossaryTermResponse]


class SchemaCacheResponse(BaseModel):
    generated_at: datetime
    expires_at: datetime
    ttl_seconds: int
    refreshed: bool


class DatabaseSchemaResponse(BaseModel):
    schemas: list[str]
    tables: list[TableSchemaResponse]
    relationships: list[ForeignKeySchemaResponse]
    glossary: BusinessGlossaryResponse
    cache: SchemaCacheResponse


def create_schema_router(
    settings: Settings,
    schema_catalog_factory: SchemaCatalogFactory = SchemaCatalogService,
) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["schema"])

    @router.get("/schema", response_model=DatabaseSchemaResponse)
    async def get_schema(request: Request, refresh: bool = False) -> DatabaseSchemaResponse:
        catalog_service = get_schema_catalog_service(request, settings, schema_catalog_factory)
        return schema_response(catalog_service.get_schema(refresh=refresh), settings)

    return router


def get_schema_catalog_service(
    request: Request,
    settings: Settings,
    schema_catalog_factory: SchemaCatalogFactory,
) -> SchemaCatalogProvider:
    cached_service = getattr(request.app.state, "schema_catalog_service", None)
    if cached_service is not None:
        return cast(SchemaCatalogProvider, cached_service)

    service = schema_catalog_factory(get_database_engine(request.app), settings)
    request.app.state.schema_catalog_service = service
    return service


def schema_response(catalog: SchemaCatalog, settings: Settings) -> DatabaseSchemaResponse:
    samples_by_column = sample_lookup(catalog.samples)
    relationships = [
        foreign_key_response(foreign_key)
        for table in catalog.database_schema.tables
        for foreign_key in table.foreign_keys
    ]

    return DatabaseSchemaResponse(
        schemas=list(catalog.database_schema.schemas),
        tables=[
            table_response(table, samples_by_column)
            for table in catalog.database_schema.tables
        ],
        relationships=relationships,
        glossary=BusinessGlossaryResponse(
            version=catalog.glossary.version,
            terms=[glossary_term_response(term) for term in catalog.glossary.terms],
        ),
        cache=SchemaCacheResponse(
            generated_at=epoch_datetime(catalog.generated_at_epoch_seconds),
            expires_at=epoch_datetime(catalog.cache_expires_at_epoch_seconds),
            ttl_seconds=settings.schema_cache_ttl_seconds,
            refreshed=catalog.refreshed,
        ),
    )


def table_response(
    table: TableSchema,
    samples_by_column: dict[tuple[str, str], tuple[str, ...]],
) -> TableSchemaResponse:
    return TableSchemaResponse(
        schema_name=table.schema_name,
        name=table.name,
        identifier=table.identifier,
        columns=[
            column_response(table, column, samples_by_column)
            for column in table.columns
        ],
        primary_key=PrimaryKeySchemaResponse(
            columns=list(table.primary_key.columns),
            name=table.primary_key.name,
        ),
        foreign_keys=[foreign_key_response(foreign_key) for foreign_key in table.foreign_keys],
    )


def column_response(
    table: TableSchema,
    column: ColumnSchema,
    samples_by_column: dict[tuple[str, str], tuple[str, ...]],
) -> ColumnSchemaResponse:
    return ColumnSchemaResponse(
        name=column.name,
        sql_type=column.sql_type,
        nullable=column.nullable,
        default=column.default,
        sample_values=list(samples_by_column.get((table.identifier, column.name), ())),
    )


def foreign_key_response(foreign_key: ForeignKeySchema) -> ForeignKeySchemaResponse:
    return ForeignKeySchemaResponse(
        name=foreign_key.name,
        source_schema=foreign_key.source_schema,
        source_table=foreign_key.source_table,
        source_columns=list(foreign_key.constrained_columns),
        referred_schema=foreign_key.referred_schema,
        referred_table=foreign_key.referred_table,
        referred_columns=list(foreign_key.referred_columns),
        display_path=foreign_key.display_path,
    )


def glossary_term_response(term: GlossaryTerm) -> GlossaryTermResponse:
    return GlossaryTermResponse(
        name=term.name,
        definition=term.definition,
        expression=term.expression,
        related_tables=list(term.related_tables),
        related_columns=list(term.related_columns),
    )


def epoch_datetime(epoch_seconds: float) -> datetime:
    return datetime.fromtimestamp(epoch_seconds, tz=UTC)
