from typing import cast
from unittest.mock import Mock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError

from app.core.config import Settings
from app.db.engine import check_database_connection
from app.main import create_app


async def test_health_endpoint_returns_status_and_version() -> None:
    mock_engine = Mock(spec=Engine)
    app = create_app(
        settings=Settings(environment="test"),
        engine_factory=lambda settings: cast(Engine, mock_engine),
        database_check=lambda engine: True,
    )
    transport = ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": "0.1.0",
        "checks": {"database": {"status": "ok"}},
    }


async def test_health_endpoint_is_stable_when_database_is_unavailable() -> None:
    mock_engine = Mock(spec=Engine)
    app = create_app(
        settings=Settings(environment="test"),
        engine_factory=lambda settings: cast(Engine, mock_engine),
        database_check=lambda engine: False,
    )
    transport = ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "degraded",
        "version": "0.1.0",
        "checks": {"database": {"status": "unavailable"}},
    }


async def test_readiness_requires_database_and_audit_storage() -> None:
    mock_engine = Mock(spec=Engine)
    app = create_app(
        settings=Settings(environment="test"),
        engine_factory=lambda settings: cast(Engine, mock_engine),
        database_check=lambda engine: True,
        audit_database_check=lambda engine: False,
    )
    transport = ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            live = await client.get("/live")
            ready = await client.get("/ready")

    assert live.status_code == 200
    assert live.json() == {"status": "ok"}
    assert ready.status_code == 503


async def test_application_lifespan_disposes_database_engine() -> None:
    mock_engine = Mock(spec=Engine)
    app = create_app(
        settings=Settings(environment="test"),
        engine_factory=lambda settings: cast(Engine, mock_engine),
        database_check=lambda engine: True,
    )

    assert not hasattr(app.state, "database_engine")

    async with app.router.lifespan_context(app):
        assert app.state.database_engine is mock_engine

    mock_engine.dispose.assert_called_once_with()


def test_database_health_logs_without_exception_details(caplog: pytest.LogCaptureFixture) -> None:
    mock_engine = Mock(spec=Engine)
    mock_engine.connect.side_effect = OperationalError(
        statement="SELECT 1",
        params=None,
        orig=RuntimeError("connection failed"),
    )

    assert check_database_connection(cast(Engine, mock_engine)) is False
    assert "Database health check failed" in caplog.text
    assert "Traceback" not in caplog.text
