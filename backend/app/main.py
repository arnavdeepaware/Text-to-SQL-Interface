from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel
from sqlalchemy import Engine

from app.api.history import QueryHistoryRepositoryFactory, create_history_router
from app.api.query import QueryExecutorFactory, SQLGeneratorFactory, create_query_router
from app.api.schema import SchemaCatalogFactory, create_schema_router
from app.core.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.request_id import RequestIDMiddleware
from app.db.engine import (
    check_database_connection,
    create_audit_database_engine,
    create_database_engine,
)
from app.db.lifecycle import (
    EngineFactory,
    database_lifespan,
    get_audit_database_engine,
    get_database_engine,
)
from app.repositories.query_history import NoopQueryHistoryRepository, QueryHistoryRepository
from app.services.query_execution import QueryExecutionService
from app.services.query_history import QueryHistoryService
from app.services.schema_catalog import SchemaCatalogService

DatabaseCheck = Callable[[Engine], bool]


class ComponentHealth(BaseModel):
    status: Literal["ok", "unavailable"]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    checks: dict[str, ComponentHealth]


def create_app(
    settings: Settings | None = None,
    engine_factory: EngineFactory = create_database_engine,
    audit_engine_factory: EngineFactory | None = None,
    database_check: DatabaseCheck = check_database_connection,
    audit_database_check: DatabaseCheck | None = None,
    schema_catalog_factory: SchemaCatalogFactory | None = None,
    sql_generator_factory: SQLGeneratorFactory | None = None,
    query_executor_factory: QueryExecutorFactory | None = None,
    query_history_repository_factory: QueryHistoryRepositoryFactory | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)
    effective_audit_engine_factory = audit_engine_factory or (
        create_audit_database_engine
        if engine_factory is create_database_engine
        else engine_factory
    )
    effective_history_repository_factory = query_history_repository_factory or (
        QueryHistoryRepository
        if engine_factory is create_database_engine
        else lambda engine: NoopQueryHistoryRepository()
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with database_lifespan(app, settings, engine_factory):
            audit_engine = effective_audit_engine_factory(settings)
            app.state.audit_database_engine = audit_engine
            try:
                if settings.query_history_enabled:
                    history_service = QueryHistoryService(
                        settings,
                        effective_history_repository_factory(audit_engine),
                    )
                    history_service.ensure_storage()
                    app.state.query_history_service = history_service
                yield
            finally:
                if audit_engine is not getattr(app.state, "database_engine", None):
                    audit_engine.dispose()
                app.state.audit_database_engine = None
                app.state.query_history_service = None

    app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)
    app.include_router(
        create_schema_router(
            settings,
            schema_catalog_factory=schema_catalog_factory or SchemaCatalogService,
        )
    )
    app.include_router(
        create_query_router(
            settings,
            schema_catalog_factory=schema_catalog_factory or SchemaCatalogService,
            sql_generator_factory=sql_generator_factory,
            query_executor_factory=query_executor_factory or QueryExecutionService,
            query_history_repository_factory=effective_history_repository_factory,
        )
    )
    app.include_router(
        create_history_router(
            settings,
            repository_factory=effective_history_repository_factory,
        )
    )

    def health_response(include_audit: bool) -> HealthResponse:
        database_ok = database_check(get_database_engine(app))
        checks = {"database": ComponentHealth(status="ok" if database_ok else "unavailable")}
        audit_ok = True
        if include_audit and settings.query_history_enabled:
            check = audit_database_check or database_check
            audit_ok = check(get_audit_database_engine(app))
            checks["audit"] = ComponentHealth(status="ok" if audit_ok else "unavailable")
        app_status: Literal["ok", "degraded"] = "ok" if database_ok and audit_ok else "degraded"

        return HealthResponse(
            status=app_status,
            version=settings.app_version,
            checks=checks,
        )

    @app.get("/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return health_response(include_audit=False)

    @app.get("/ready", response_model=HealthResponse)
    async def ready() -> HealthResponse:
        response = health_response(include_audit=True)
        if response.status != "ok":
            from fastapi import HTTPException, status

            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=response.model_dump(),
            )
        return response

    return app


app = create_app()
