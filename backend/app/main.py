from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel
from sqlalchemy import Engine

from app.core.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.db.engine import check_database_connection, create_database_engine
from app.db.lifecycle import EngineFactory, database_lifespan, get_database_engine

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
    database_check: DatabaseCheck = check_database_connection,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with database_lifespan(app, settings, engine_factory):
            yield

    app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
    register_exception_handlers(app)

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        database_ok = database_check(get_database_engine(app))
        database_status: Literal["ok", "unavailable"] = "ok" if database_ok else "unavailable"
        app_status: Literal["ok", "degraded"] = "ok" if database_ok else "degraded"

        return HealthResponse(
            status=app_status,
            version=settings.app_version,
            checks={"database": ComponentHealth(status=database_status)},
        )

    return app


app = create_app()
