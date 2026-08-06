from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    app_name: str = "Text-to-SQL Interface"
    app_version: str = "0.1.0"
    environment: Literal["local", "test", "development", "staging", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    model_config = SettingsConfigDict(
        env_prefix="TEXT_TO_SQL_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
