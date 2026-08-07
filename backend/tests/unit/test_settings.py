from pydantic import SecretStr
from pytest import MonkeyPatch

from app.core.config import Settings
from app.db.engine import build_database_url


def test_settings_use_default_values(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("TEXT_TO_SQL_APP_NAME", raising=False)
    monkeypatch.delenv("TEXT_TO_SQL_APP_VERSION", raising=False)
    monkeypatch.delenv("TEXT_TO_SQL_ENVIRONMENT", raising=False)
    monkeypatch.delenv("TEXT_TO_SQL_LOG_LEVEL", raising=False)
    monkeypatch.delenv("TEXT_TO_SQL_DATABASE_HOST", raising=False)
    monkeypatch.delenv("TEXT_TO_SQL_DATABASE_PORT", raising=False)
    monkeypatch.delenv("TEXT_TO_SQL_DATABASE_NAME", raising=False)
    monkeypatch.delenv("TEXT_TO_SQL_DATABASE_USER", raising=False)
    monkeypatch.delenv("TEXT_TO_SQL_DATABASE_PASSWORD", raising=False)

    settings = Settings()

    assert settings.app_name == "Text-to-SQL Interface"
    assert settings.app_version == "0.1.0"
    assert settings.environment == "local"
    assert settings.log_level == "INFO"
    assert settings.database_host == "127.0.0.1"
    assert settings.database_port == 5432
    assert settings.database_name == "text_to_sql"
    assert settings.database_user == "text_to_sql_reader"
    assert settings.sql_guardrail_max_subquery_depth == 3
    assert settings.sql_guardrail_max_returned_rows == 1000
    assert settings.sql_guardrail_explain_timeout_ms == 1000
    assert settings.sql_guardrail_max_plan_rows == 50000
    assert settings.sql_guardrail_max_plan_total_cost == 100000.0
    assert settings.sql_execution_max_rows == 1000
    assert settings.sql_execution_lock_timeout_ms == 500


def test_settings_read_environment_overrides(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("TEXT_TO_SQL_APP_VERSION", "9.9.9")
    monkeypatch.setenv("TEXT_TO_SQL_ENVIRONMENT", "test")
    monkeypatch.setenv("TEXT_TO_SQL_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("TEXT_TO_SQL_DATABASE_HOST", "db.example.test")
    monkeypatch.setenv("TEXT_TO_SQL_DATABASE_PORT", "6543")
    monkeypatch.setenv("TEXT_TO_SQL_DATABASE_NAME", "analytics")
    monkeypatch.setenv("TEXT_TO_SQL_DATABASE_USER", "reader")
    monkeypatch.setenv("TEXT_TO_SQL_DATABASE_PASSWORD", "not-a-real-secret")

    settings = Settings()

    assert settings.app_version == "9.9.9"
    assert settings.environment == "test"
    assert settings.log_level == "DEBUG"
    assert settings.database_host == "db.example.test"
    assert settings.database_port == 6543
    assert settings.database_name == "analytics"
    assert settings.database_user == "reader"
    assert settings.database_password.get_secret_value() == "not-a-real-secret"


def test_database_url_hides_password_by_default() -> None:
    settings = Settings(
        database_user="reader",
        database_password=SecretStr("sensitive-value"),
        database_host="localhost",
        database_port=5432,
        database_name="text_to_sql",
    )

    url = build_database_url(settings)

    assert str(url) == "postgresql+psycopg://reader:***@localhost:5432/text_to_sql"
    assert "sensitive-value" not in str(url)
