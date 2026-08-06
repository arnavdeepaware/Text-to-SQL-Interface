from fastapi import FastAPI
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging


class HealthResponse(BaseModel):
    status: str
    version: str


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)

    app = FastAPI(title=settings.app_name, version=settings.app_version)
    register_exception_handlers(app)

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", version=settings.app_version)

    return app


app = create_app()
