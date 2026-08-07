from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from app.core.config import Settings
from app.domain.glossary import GlossaryTerm
from app.domain.prompt import FewShotExample, PromptMessage, SQLGenerationPrompt
from app.domain.schema import ColumnSchema, DatabaseSchema, TableSchema
from app.domain.schema_catalog import SchemaCatalog
from app.domain.schema_retrieval import SchemaRetrievalResult
from app.services.few_shot_loader import FewShotExampleLoader
from app.services.schema_sampling import sample_lookup


class PromptContextError(ValueError):
    """Raised when prompt context cannot be constructed safely."""


class SchemaAwarePromptEngine:
    """Build deterministic provider-neutral prompts from retrieved schema context."""

    def __init__(
        self,
        settings: Settings,
        few_shot_examples: tuple[FewShotExample, ...] | None = None,
    ) -> None:
        self._settings = settings
        self._few_shot_examples = few_shot_examples

    def build_prompt(
        self,
        question: str,
        catalog: SchemaCatalog,
        retrieval: SchemaRetrievalResult,
    ) -> SQLGenerationPrompt:
        if question != retrieval.question:
            raise PromptContextError("Prompt question must match retrieval question")

        selected_table_ids = {table.identifier for table in retrieval.selected_tables}
        selected_column_ids = {column.identifier for column in retrieval.selected_columns}
        tables = selected_tables(catalog.database_schema, selected_table_ids)
        samples_by_column = sample_lookup(catalog.samples)
        glossary_terms = selected_glossary_terms(catalog.glossary.terms, retrieval.glossary_terms)
        few_shots = self._select_few_shots(retrieval)

        context = render_context(
            sql_dialect=self._settings.prompt_sql_dialect,
            tables=tables,
            selected_column_ids=selected_column_ids,
            samples_by_column=samples_by_column,
            glossary_terms=glossary_terms,
            retrieval=retrieval,
            few_shots=few_shots,
        )
        truncated_context, truncated = deterministic_truncate(
            context,
            self._settings.prompt_context_budget_chars,
        )

        messages = (
            PromptMessage("system", system_instructions(self._settings.prompt_sql_dialect)),
            PromptMessage("user", user_message(question, truncated_context)),
        )
        return SQLGenerationPrompt(
            original_question=question,
            sql_dialect=self._settings.prompt_sql_dialect,
            messages=messages,
            selected_few_shot_ids=tuple(example.example_id for example in few_shots),
            context_budget_chars=self._settings.prompt_context_budget_chars,
            context_chars=len(truncated_context),
            truncated=truncated,
        )

    def _select_few_shots(
        self,
        retrieval: SchemaRetrievalResult,
    ) -> tuple[FewShotExample, ...]:
        examples = self._few_shot_examples
        if examples is None:
            examples = FewShotExampleLoader().load()
        return select_few_shots(
            retrieval,
            examples,
            self._settings.prompt_max_few_shot_examples,
        )


def system_instructions(sql_dialect: str) -> str:
    forbidden_sql = (
        "Never use INSERT, UPDATE, DELETE, MERGE, UPSERT, ALTER, DROP, CREATE, "
        "TRUNCATE, GRANT, REVOKE, COPY, CALL, EXECUTE, or transaction-control statements."
    )
    return "\n".join(
        (
            "You generate SQL for a Text-to-SQL system.",
            f"SQL dialect: {sql_dialect}.",
            "Use only the schema context provided in the user message.",
            "The SQL must be read-only: SELECT statements only.",
            forbidden_sql,
            (
                "Never access schemas, tables, columns, or sample values that are not present "
                "in the provided context."
            ),
            (
                "Return structured JSON only with keys: sql, explanation, referenced_tables, "
                "referenced_columns, assumptions."
            ),
            (
                "If the question cannot be answered from the context, return sql as null and "
                "explain why."
            ),
        )
    )


def user_message(question: str, context: str) -> str:
    return "\n".join(
        (
            "Original question:",
            question,
            "",
            "Retrieved schema context:",
            context,
        )
    )


def render_context(
    sql_dialect: str,
    tables: tuple[TableSchema, ...],
    selected_column_ids: set[str],
    samples_by_column: dict[tuple[str, str], tuple[str, ...]],
    glossary_terms: tuple[GlossaryTerm, ...],
    retrieval: SchemaRetrievalResult,
    few_shots: tuple[FewShotExample, ...],
) -> str:
    sections = [
        f"SQL dialect: {sql_dialect}",
        render_tables(tables, selected_column_ids, samples_by_column),
        render_relationships(tables, retrieval),
        render_glossary(glossary_terms),
        render_few_shots(few_shots),
        render_retrieval_notes(retrieval),
    ]
    return "\n\n".join(section for section in sections if section)


def render_tables(
    tables: tuple[TableSchema, ...],
    selected_column_ids: set[str],
    samples_by_column: dict[tuple[str, str], tuple[str, ...]],
) -> str:
    if not tables:
        return "Tables: none"

    lines = ["Tables:"]
    for table in tables:
        lines.append(f"- {table.identifier}")
        selected_columns = tuple(
            column
            for column in table.columns
            if f"{table.identifier}.{column.name}" in selected_column_ids
        )
        if not selected_columns:
            lines.append("  columns: none selected")
            continue
        column_lines = [
            render_column(table, column, samples_by_column)
            for column in selected_columns
        ]
        lines.extend(f"  - {column_line}" for column_line in column_lines)
    return "\n".join(lines)


def render_column(
    table: TableSchema,
    column: ColumnSchema,
    samples_by_column: dict[tuple[str, str], tuple[str, ...]],
) -> str:
    nullable = "nullable" if column.nullable else "not nullable"
    parts = [f"{column.name} {column.sql_type} {nullable}"]
    if column.default is not None:
        parts.append(f"default={column.default}")
    samples = samples_by_column.get((table.identifier, column.name), ())
    if samples:
        sample_text = ", ".join(repr(value) for value in samples)
        parts.append(f"safe_samples=[{sample_text}]")
    return "; ".join(parts)


def render_relationships(
    tables: tuple[TableSchema, ...],
    retrieval: SchemaRetrievalResult,
) -> str:
    selected_table_ids = {table.identifier for table in tables}
    direct_relationships = sorted(
        {
            foreign_key.display_path
            for table in tables
            for foreign_key in table.foreign_keys
            if foreign_key.referred_table_identifier in selected_table_ids
            and foreign_key.source_table_identifier in selected_table_ids
        }
    )
    path_relationships = tuple(path.display_path for path in retrieval.relationship_paths)

    if not direct_relationships and not path_relationships:
        return "Relationships: none selected"

    lines = ["Relationships:"]
    for relationship in direct_relationships:
        lines.append(f"- direct: {relationship}")
    for path in path_relationships:
        lines.append(f"- selected_path: {path}")
    return "\n".join(lines)


def render_glossary(terms: tuple[GlossaryTerm, ...]) -> str:
    if not terms:
        return "Business glossary: none selected"

    lines = ["Business glossary:"]
    for term in terms:
        lines.append(f"- {term.name}: {term.definition} Expression: {term.expression}")
    return "\n".join(lines)


def render_few_shots(examples: tuple[FewShotExample, ...]) -> str:
    if not examples:
        return "Few-shot examples: none selected"

    lines = ["Few-shot examples:"]
    for example in examples:
        lines.append(f"- id: {example.example_id}")
        lines.append(f"  question: {example.question}")
        lines.append(f"  sql: {example.sql}")
    return "\n".join(lines)


def render_retrieval_notes(retrieval: SchemaRetrievalResult) -> str:
    selected_tables = ", ".join(table.identifier for table in retrieval.selected_tables)
    selected_columns = ", ".join(column.identifier for column in retrieval.selected_columns)
    return "\n".join(
        (
            "Retrieval notes:",
            f"- strategy: {retrieval.strategy}",
            f"- selected_tables: {selected_tables or 'none'}",
            f"- selected_columns: {selected_columns or 'none'}",
        )
    )


def selected_tables(
    database_schema: DatabaseSchema,
    selected_table_ids: set[str],
) -> tuple[TableSchema, ...]:
    return tuple(
        table for table in database_schema.tables if table.identifier in selected_table_ids
    )


def selected_glossary_terms(
    terms: tuple[GlossaryTerm, ...],
    selected_names: tuple[str, ...],
) -> tuple[GlossaryTerm, ...]:
    selected = set(selected_names)
    return tuple(term for term in terms if term.name in selected)


def select_few_shots(
    retrieval: SchemaRetrievalResult,
    examples: tuple[FewShotExample, ...],
    max_examples: int,
) -> tuple[FewShotExample, ...]:
    if max_examples == 0:
        return ()

    selected_tables = {table.table_name for table in retrieval.selected_tables}
    selected_columns = {
        strip_schema(column.identifier)
        for column in retrieval.selected_columns
    }
    glossary_terms = set(retrieval.glossary_terms)
    question_tokens = tokenize(retrieval.question)

    scored = [
        (
            few_shot_score(
                example,
                selected_tables,
                selected_columns,
                glossary_terms,
                question_tokens,
            ),
            example,
        )
        for example in examples
    ]
    relevant = []
    for score, example in scored:
        if score <= 0 or not set(example.required_tables) <= selected_tables:
            continue
        if glossary_terms and not set(example.glossary_terms) & glossary_terms:
            continue
        relevant.append((score, example))
    relevant.sort(key=lambda item: (-item[0], item[1].example_id))
    return tuple(example for _, example in relevant[:max_examples])


def few_shot_score(
    example: FewShotExample,
    selected_tables: set[str],
    selected_columns: set[str],
    glossary_terms: set[str],
    question_tokens: set[str],
) -> int:
    score = 0
    score += 20 * len(set(example.required_tables) & selected_tables)
    score += 10 * len(set(example.required_columns) & selected_columns)
    score += 25 * len(set(example.glossary_terms) & glossary_terms)
    score += 5 * len(set(example.tags) & question_tokens)
    score += 3 * len(tokenize(example.question) & question_tokens)
    return score


def strip_schema(identifier: str) -> str:
    parts = identifier.split(".")
    if len(parts) >= 3:
        return ".".join(parts[-2:])
    return identifier


def tokenize(text: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", text).casefold().replace("_", " ")
    return set(re.findall(r"[a-z0-9]+", normalized))


def deterministic_truncate(text: str, budget_chars: int) -> tuple[str, bool]:
    if len(text) <= budget_chars:
        return text, False

    marker = "\n[...prompt context truncated deterministically...]\n"
    if budget_chars <= len(marker):
        return marker[:budget_chars], True

    keep = budget_chars - len(marker)
    prefix_chars = max(1, int(keep * 0.75))
    suffix_chars = keep - prefix_chars
    return f"{text[:prefix_chars]}{marker}{text[-suffix_chars:]}", True


def values_for_log(value: Iterable[str]) -> tuple[str, ...]:
    """Helper for future log-safe metadata; values are identifiers, not secrets."""

    return tuple(value)
