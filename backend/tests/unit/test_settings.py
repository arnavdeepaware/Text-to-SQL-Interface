from pydantic import SecretStr
from pytest import MonkeyPatch

from app.core.config import Settings
from app.db.engine import build_audit_database_url, build_database_url


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
    monkeypatch.delenv("TEXT_TO_SQL_AUDIT_DATABASE_USER", raising=False)
    monkeypatch.delenv("TEXT_TO_SQL_AUDIT_DATABASE_PASSWORD", raising=False)

    settings = Settings()

    assert settings.app_name == "Text-to-SQL Interface"
    assert settings.app_version == "0.1.0"
    assert settings.environment == "local"
    assert settings.log_level == "INFO"
    assert settings.database_host == "127.0.0.1"
    assert settings.database_port == 5432
    assert settings.database_name == "text_to_sql"
    assert settings.database_user == "text_to_sql_reader"
    assert settings.audit_database_user == "text_to_sql_audit_writer"
    assert settings.sql_generation_fake_profile == "placeholder"
    assert settings.query_history_enabled is True
    assert settings.query_history_default_limit == 25
    assert settings.query_history_max_limit == 100
    assert settings.query_feedback_comment_max_chars == 500
    assert settings.query_history_retention_days == 30
    assert settings.query_feedback_retention_days == 90
    assert settings.sql_guardrail_max_subquery_depth == 3
    assert settings.sql_guardrail_max_returned_rows == 1000
    assert settings.sql_guardrail_explain_timeout_ms == 1000
    assert settings.sql_guardrail_max_plan_rows == 50000
    assert settings.sql_guardrail_max_plan_total_cost == 100000.0
    assert settings.sql_execution_max_rows == 1000
    assert settings.sql_execution_lock_timeout_ms == 500
    assert settings.deterministic_validation_enabled is True
    assert settings.result_sanity_null_heavy_threshold == 0.8
    assert settings.result_sanity_min_percentage == 0.0
    assert settings.result_sanity_max_percentage == 100.0
    assert settings.result_sanity_min_date == "2020-01-01"
    assert settings.result_sanity_max_date == "2030-12-31"
    assert settings.confidence_semantic_enabled is False
    assert settings.confidence_alignment_provider == "openai"
    assert settings.confidence_alignment_timeout_seconds == 3.0
    assert settings.confidence_alignment_max_retries == 0
    assert settings.confidence_multi_query_enabled is False
    assert settings.confidence_multi_query_max_alternates == 1
    assert settings.confidence_multi_query_max_result_rows == 100
    assert settings.confidence_multi_query_decimal_abs_tol == 0.000001
    assert settings.confidence_weight_sql_syntax == 0.10
    assert settings.confidence_weight_guardrail_approval == 0.15
    assert settings.confidence_weight_schema_coverage == 0.20
    assert settings.confidence_weight_result_sanity == 0.20
    assert settings.confidence_weight_semantic_alignment == 0.15
    assert settings.confidence_weight_multi_query_agreement == 0.18
    assert settings.confidence_weight_model_reported == 0.02
    assert settings.confidence_high_threshold == 0.85
    assert settings.confidence_medium_threshold == 0.70
    assert settings.confidence_low_threshold == 0.50
    assert settings.confidence_blocked_threshold == 0.35


def test_settings_read_environment_overrides(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("TEXT_TO_SQL_APP_VERSION", "9.9.9")
    monkeypatch.setenv("TEXT_TO_SQL_ENVIRONMENT", "test")
    monkeypatch.setenv("TEXT_TO_SQL_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("TEXT_TO_SQL_DATABASE_HOST", "db.example.test")
    monkeypatch.setenv("TEXT_TO_SQL_DATABASE_PORT", "6543")
    monkeypatch.setenv("TEXT_TO_SQL_DATABASE_NAME", "analytics")
    monkeypatch.setenv("TEXT_TO_SQL_DATABASE_USER", "reader")
    monkeypatch.setenv("TEXT_TO_SQL_DATABASE_PASSWORD", "not-a-real-secret")
    monkeypatch.setenv("TEXT_TO_SQL_AUDIT_DATABASE_USER", "audit_writer")
    monkeypatch.setenv("TEXT_TO_SQL_AUDIT_DATABASE_PASSWORD", "audit-secret")
    monkeypatch.setenv("TEXT_TO_SQL_QUERY_HISTORY_RETENTION_DAYS", "45")

    settings = Settings()

    assert settings.app_version == "9.9.9"
    assert settings.environment == "test"
    assert settings.log_level == "DEBUG"
    assert settings.database_host == "db.example.test"
    assert settings.database_port == 6543
    assert settings.database_name == "analytics"
    assert settings.database_user == "reader"
    assert settings.database_password.get_secret_value() == "not-a-real-secret"
    assert settings.audit_database_user == "audit_writer"
    assert settings.audit_database_password.get_secret_value() == "audit-secret"
    assert settings.query_history_retention_days == 45


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


def test_audit_database_url_uses_separate_credentials() -> None:
    settings = Settings(
        database_user="reader",
        database_password=SecretStr("reader-secret"),
        audit_database_user="audit_writer",
        audit_database_password=SecretStr("audit-secret"),
        database_host="localhost",
        database_port=5432,
        database_name="text_to_sql",
    )

    url = build_audit_database_url(settings)

    assert str(url) == "postgresql+psycopg://audit_writer:***@localhost:5432/text_to_sql"
    assert "audit-secret" not in str(url)
