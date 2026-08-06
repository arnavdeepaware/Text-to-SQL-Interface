from pytest import MonkeyPatch

from app.core.config import Settings


def test_settings_use_default_values(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("TEXT_TO_SQL_APP_NAME", raising=False)
    monkeypatch.delenv("TEXT_TO_SQL_APP_VERSION", raising=False)
    monkeypatch.delenv("TEXT_TO_SQL_ENVIRONMENT", raising=False)
    monkeypatch.delenv("TEXT_TO_SQL_LOG_LEVEL", raising=False)

    settings = Settings()

    assert settings.app_name == "Text-to-SQL Interface"
    assert settings.app_version == "0.1.0"
    assert settings.environment == "local"
    assert settings.log_level == "INFO"


def test_settings_read_environment_overrides(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("TEXT_TO_SQL_APP_VERSION", "9.9.9")
    monkeypatch.setenv("TEXT_TO_SQL_ENVIRONMENT", "test")
    monkeypatch.setenv("TEXT_TO_SQL_LOG_LEVEL", "DEBUG")

    settings = Settings()

    assert settings.app_version == "9.9.9"
    assert settings.environment == "test"
    assert settings.log_level == "DEBUG"
