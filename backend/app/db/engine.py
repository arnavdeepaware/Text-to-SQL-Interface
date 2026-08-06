import logging

from sqlalchemy import URL, Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings

logger = logging.getLogger(__name__)


def build_database_url(settings: Settings) -> URL:
    return URL.create(
        "postgresql+psycopg",
        username=settings.database_user,
        password=settings.database_password.get_secret_value(),
        host=settings.database_host,
        port=settings.database_port,
        database=settings.database_name,
    )


def create_database_engine(settings: Settings) -> Engine:
    return create_engine(
        build_database_url(settings),
        pool_pre_ping=True,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_recycle=1_800,
        connect_args={
            "connect_timeout": settings.database_connect_timeout_seconds,
            "application_name": "text-to-sql-backend",
            "options": (
                f"-c statement_timeout={settings.database_statement_timeout_ms} "
                f"-c idle_in_transaction_session_timeout={settings.database_statement_timeout_ms}"
            ),
        },
    )


def check_database_connection(engine: Engine) -> bool:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.warning("Database health check failed")
        return False

    return True
