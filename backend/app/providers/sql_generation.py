from typing import Protocol

from app.domain.prompt import SQLGenerationPrompt
from app.domain.sql_generation import SQLGenerationDraft


class SQLGenerationError(RuntimeError):
    """Base typed application error for provider-neutral SQL generation failures."""

    public_code = "sql_generation_error"
    public_message = "SQL generation failed."


class SQLGenerationMalformedOutputError(SQLGenerationError):
    public_code = "sql_generation_malformed_output"
    public_message = "The SQL provider returned malformed structured output."


class SQLGenerationProviderTimeoutError(SQLGenerationError):
    public_code = "sql_generation_provider_timeout"
    public_message = "The SQL provider timed out."


class SQLGenerationRateLimitError(SQLGenerationError):
    public_code = "sql_generation_rate_limited"
    public_message = "The SQL provider is rate limited."


class SQLGenerationCredentialsUnavailableError(SQLGenerationError):
    public_code = "sql_generation_credentials_unavailable"
    public_message = "SQL generation credentials are unavailable."


class SQLGenerationProviderUnavailableError(SQLGenerationError):
    public_code = "sql_generation_provider_unavailable"
    public_message = "The SQL provider is unavailable."


class SQLGenerator(Protocol):
    """Provider-neutral SQL draft generator."""

    def generate(self, prompt: SQLGenerationPrompt) -> SQLGenerationDraft: ...
