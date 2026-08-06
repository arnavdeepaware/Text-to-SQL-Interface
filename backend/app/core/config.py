from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    app_name: str = "Text-to-SQL Interface"
    app_version: str = "0.1.0"
    environment: Literal["local", "test", "development", "staging", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_host: str = "127.0.0.1"
    database_port: int = Field(default=5432, ge=1, le=65535)
    database_name: str = "text_to_sql"
    database_user: str = "text_to_sql_reader"
    database_password: SecretStr = SecretStr("text_to_sql_reader_local_password")
    database_connect_timeout_seconds: int = Field(default=2, ge=1, le=30)
    database_statement_timeout_ms: int = Field(default=5_000, ge=100, le=60_000)
    database_pool_size: int = Field(default=5, ge=1, le=20)
    database_max_overflow: int = Field(default=0, ge=0, le=20)

    model_config = SettingsConfigDict(
        env_prefix="TEXT_TO_SQL_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
