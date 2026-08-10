from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import cast

from fastapi import FastAPI
from sqlalchemy import Engine

from app.core.config import Settings
from app.db.engine import create_database_engine

EngineFactory = Callable[[Settings], Engine]


def get_database_engine(
    app: FastAPI,
) -> Engine:
    engine = getattr(app.state, "database_engine", None)
    if engine is None:
        msg = "Database engine is not initialized."
        raise RuntimeError(msg)

    return cast(Engine, engine)


def get_audit_database_engine(app: FastAPI) -> Engine:
    engine = getattr(app.state, "audit_database_engine", None)
    if engine is None:
        msg = "Audit database engine is not initialized."
        raise RuntimeError(msg)

    return cast(Engine, engine)


@asynccontextmanager
async def database_lifespan(
    app: FastAPI,
    settings: Settings,
    engine_factory: EngineFactory = create_database_engine,
) -> AsyncIterator[None]:
    engine = engine_factory(settings)
    app.state.database_engine = engine

    try:
        yield
    finally:
        engine.dispose()
        app.state.database_engine = None
