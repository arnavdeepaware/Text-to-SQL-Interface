from dataclasses import dataclass
from typing import Literal

PromptRole = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class PromptMessage:
    """Provider-neutral chat message for SQL generation."""

    role: PromptRole
    content: str


@dataclass(frozen=True)
class FewShotExample:
    """Schema-specific few-shot example loaded from a resource file."""

    example_id: str
    question: str
    sql: str
    required_tables: tuple[str, ...]
    required_columns: tuple[str, ...] = ()
    glossary_terms: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class SQLGenerationPrompt:
    """Inspectable prompt package for provider-neutral Text-to-SQL generation."""

    original_question: str
    sql_dialect: str
    messages: tuple[PromptMessage, ...]
    selected_few_shot_ids: tuple[str, ...]
    context_budget_chars: int
    context_chars: int
    truncated: bool

    @property
    def text(self) -> str:
        return "\n\n".join(
            f"{message.role.upper()}:\n{message.content}" for message in self.messages
        )

    def safe_log_summary(self) -> dict[str, object]:
        """Return non-secret metadata safe for logs and tests."""

        return {
            "original_question": self.original_question,
            "sql_dialect": self.sql_dialect,
            "message_count": len(self.messages),
            "selected_few_shot_ids": self.selected_few_shot_ids,
            "context_budget_chars": self.context_budget_chars,
            "context_chars": self.context_chars,
            "truncated": self.truncated,
        }
