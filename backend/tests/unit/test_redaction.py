from app.core.redaction import redact_object, redact_text


def test_redact_text_masks_likely_secrets() -> None:
    redacted = redact_text(
        "Use api_key=supersecretvalue123 and Authorization: Bearer abcdefghijklmnop"
    )

    assert redacted.redacted is True
    assert "supersecretvalue123" not in redacted.value
    assert "abcdefghijklmnop" not in redacted.value
    assert "[REDACTED]" in redacted.value


def test_redact_object_drops_secret_keys_and_redacts_nested_values() -> None:
    redacted = redact_object(
        {
            "provider_name": "fake",
            "api_key": "secret",
            "nested": {"comment": "password=hunter2hunter2"},
        }
    )

    assert redacted == {
        "provider_name": "fake",
        "nested": {"comment": "password=[REDACTED]"},
    }
