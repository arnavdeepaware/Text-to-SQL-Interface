from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any, Protocol, TypeGuard

import sqlglot
from sqlglot import exp
from sqlglot.errors import ErrorLevel, ParseError
from sqlglot.optimizer.scope import Scope, traverse_scope

from app.core.config import Settings
from app.domain.schema import DatabaseSchema
from app.domain.schema_catalog import SchemaCatalog
from app.domain.sql_guardrails import (
    ReferencedColumn,
    ReferencedTable,
    SQLReferenceSource,
    SQLStatementType,
    SQLValidationFinding,
    SQLValidationMetadata,
    SQLValidationResult,
)

POSTGRES_DIALECT = "postgres"
logger = logging.getLogger(__name__)


class SQLGuardrailValidationError(RuntimeError):
    """Raised when generated SQL fails fail-closed validation."""

    public_code = "sql_validation_failed"
    public_message = "Generated SQL failed safety validation."

    def __init__(self, result: SQLValidationResult) -> None:
        self.result = result
        codes = ", ".join(finding.code for finding in result.findings)
        super().__init__(codes or self.public_message)


@dataclass(frozen=True)
class CatalogTable:
    schema_name: str
    name: str
    columns: frozenset[str]

    @property
    def identifier(self) -> str:
        return f"{self.schema_name}.{self.name}"


@dataclass(frozen=True)
class SourceInfo:
    name: str
    source: SQLReferenceSource
    columns: frozenset[str]
    table: CatalogTable | None = None

    @property
    def table_identifier(self) -> str | None:
        if self.table is None:
            return None
        return self.table.identifier


@dataclass(frozen=True)
class SQLPolicyContext:
    original_sql: str
    statements: tuple[exp.Expression, ...]
    statement: exp.Expression | None
    settings: Settings


class GuardrailRule(Protocol):
    """Composable SQL policy rule."""

    name: str

    def evaluate(self, context: SQLPolicyContext) -> tuple[SQLValidationFinding, ...]: ...


class SingleStatementRule:
    name = "SingleStatementRule"

    def evaluate(self, context: SQLPolicyContext) -> tuple[SQLValidationFinding, ...]:
        if len(context.statements) == 1:
            return ()
        return (
            finding(
                self.name,
                "multiple_statements",
                "Generated SQL must contain exactly one statement.",
            ),
        )


class StatementClassificationRule:
    name = "StatementClassificationRule"

    def evaluate(self, context: SQLPolicyContext) -> tuple[SQLValidationFinding, ...]:
        if context.statement is None:
            return ()
        statement_type = classify_statement(context.statement)
        if statement_type == "select":
            return ()
        if statement_type == "command":
            return (
                finding(
                    self.name,
                    "unclassified_statement",
                    "Generated SQL contains a command the parser cannot classify safely.",
                ),
            )
        return (
            finding(
                self.name,
                "unsupported_statement_type",
                "Generated SQL must be a SELECT statement.",
            ),
        )


class StructuralMutationRule:
    name = "StructuralMutationRule"

    def evaluate(self, context: SQLPolicyContext) -> tuple[SQLValidationFinding, ...]:
        if context.statement is None:
            return ()

        findings: list[SQLValidationFinding] = []
        for node_name in unsafe_node_names(context.statement):
            findings.append(
                finding(
                    self.name,
                    "blocked_statement_node",
                    f"Generated SQL contains blocked statement node `{node_name}`.",
                )
            )
        return tuple(findings)


class SelectIntoRule:
    name = "SelectIntoRule"

    def evaluate(self, context: SQLPolicyContext) -> tuple[SQLValidationFinding, ...]:
        if context.statement is None:
            return ()
        has_select_into = any(
            select.args.get("into") is not None
            for select in context.statement.find_all(exp.Select)
        )
        if has_select_into:
            return (
                finding(
                    self.name,
                    "select_into_blocked",
                    "Generated SQL must not use SELECT INTO.",
                ),
            )
        return ()


class LockingClauseRule:
    name = "LockingClauseRule"

    def evaluate(self, context: SQLPolicyContext) -> tuple[SQLValidationFinding, ...]:
        if context.statement is None:
            return ()
        locks = tuple(context.statement.find_all(exp.Lock))
        if not locks:
            return ()
        return tuple(
            finding(
                self.name,
                "locking_clause_blocked",
                "Generated SQL must not use locking clauses such as FOR UPDATE.",
            )
            for _lock in locks
        )


class MaxSubqueryDepthRule:
    name = "MaxSubqueryDepthRule"

    def evaluate(self, context: SQLPolicyContext) -> tuple[SQLValidationFinding, ...]:
        if context.statement is None:
            return ()
        depth = max_subquery_depth(context.statement)
        if depth <= context.settings.sql_guardrail_max_subquery_depth:
            return ()
        return (
            finding(
                self.name,
                "subquery_depth_exceeded",
                "Generated SQL exceeds the maximum allowed subquery depth.",
            ),
        )


class LimitRule:
    name = "LimitRule"

    def evaluate(self, context: SQLPolicyContext) -> tuple[SQLValidationFinding, ...]:
        if not isinstance(context.statement, exp.Select):
            return ()
        limit = context.statement.args.get("limit")
        if limit is None:
            return ()
        parsed_limit = literal_limit_value(limit)
        if parsed_limit is None:
            return (
                finding(
                    self.name,
                    "unclassifiable_limit",
                    "Generated SQL uses a LIMIT value that cannot be classified safely.",
                ),
            )
        if parsed_limit < 0:
            return (
                finding(
                    self.name,
                    "invalid_limit",
                    "Generated SQL uses a negative LIMIT.",
                ),
            )
        return ()

    def apply(self, statement: exp.Expression, settings: Settings) -> LimitRewriteResult:
        if not isinstance(statement, exp.Select):
            return LimitRewriteResult(statement=statement, effective_limit=None)

        rewritten = statement.copy()
        limit = rewritten.args.get("limit")
        if limit is None:
            rewritten = rewritten.limit(settings.sql_guardrail_max_returned_rows)
            return LimitRewriteResult(
                statement=rewritten,
                effective_limit=settings.sql_guardrail_max_returned_rows,
                limit_was_added=True,
            )

        parsed_limit = literal_limit_value(limit)
        if parsed_limit is None:
            return LimitRewriteResult(statement=rewritten, effective_limit=None)
        if parsed_limit > settings.sql_guardrail_max_returned_rows:
            rewritten = rewritten.limit(settings.sql_guardrail_max_returned_rows)
            return LimitRewriteResult(
                statement=rewritten,
                effective_limit=settings.sql_guardrail_max_returned_rows,
                limit_was_reduced=True,
            )
        return LimitRewriteResult(statement=rewritten, effective_limit=parsed_limit)


@dataclass(frozen=True)
class LimitRewriteResult:
    statement: exp.Expression
    effective_limit: int | None
    limit_was_added: bool = False
    limit_was_reduced: bool = False


DEFAULT_RULES: tuple[GuardrailRule, ...] = (
    SingleStatementRule(),
    StatementClassificationRule(),
    StructuralMutationRule(),
    SelectIntoRule(),
    LockingClauseRule(),
    MaxSubqueryDepthRule(),
    LimitRule(),
)


class GeneratedSQLValidator:
    """Validate generated SQL through PostgreSQL AST parsing and schema resolution."""

    def __init__(
        self,
        settings: Settings | None = None,
        rules: tuple[GuardrailRule, ...] = DEFAULT_RULES,
    ) -> None:
        self._settings = settings or Settings()
        self._rules = rules

    def validate(self, sql: str, catalog: SchemaCatalog) -> SQLValidationResult:
        stripped_sql = sql.strip()
        if not stripped_sql:
            result = invalid_result(
                sql,
                "ParseRule",
                "empty_sql",
                "Generated SQL is empty.",
            )
            log_policy_decision(result)
            return result

        try:
            parsed = sqlglot.parse(
                stripped_sql,
                read=POSTGRES_DIALECT,
                error_level=ErrorLevel.RAISE,
            )
        except ParseError:
            result = invalid_result(
                sql,
                "ParseRule",
                "malformed_sql",
                "Generated SQL could not be parsed as PostgreSQL.",
            )
            log_policy_decision(result)
            return result

        statements = tuple(statement for statement in parsed if statement is not None)
        if not statements:
            result = invalid_result(
                sql,
                "ParseRule",
                "malformed_sql",
                "Generated SQL could not be parsed as PostgreSQL.",
            )
            log_policy_decision(result)
            return result

        statement = statements[0] if len(statements) == 1 else None
        context = SQLPolicyContext(
            original_sql=sql,
            statements=statements,
            statement=statement,
            settings=self._settings,
        )
        findings = [finding for rule in self._rules for finding in rule.evaluate(context)]

        if statement is None:
            result = SQLValidationResult(
                sql=sql,
                original_sql=sql,
                valid=False,
                metadata=SQLValidationMetadata(statement_type="unknown"),
                findings=tuple(findings),
            )
            log_policy_decision(result)
            return result

        metadata = extract_metadata(statement, catalog.database_schema, findings)
        if has_error_findings(findings):
            result = SQLValidationResult(
                sql=sql,
                original_sql=sql,
                valid=False,
                metadata=metadata,
                findings=tuple(findings),
            )
            log_policy_decision(result)
            return result

        limit_result = limit_rule(self._rules).apply(statement, self._settings)
        rewritten_sql = limit_result.statement.sql(dialect=POSTGRES_DIALECT)
        reparsed = reparse_single_statement(rewritten_sql)
        if reparsed is None:
            findings.append(
                finding(
                    "LimitRule",
                    "limit_rewrite_invalid",
                    "Generated SQL LIMIT rewrite did not produce valid PostgreSQL.",
                )
            )
            result = SQLValidationResult(
                sql=sql,
                original_sql=sql,
                valid=False,
                metadata=metadata,
                findings=tuple(findings),
            )
            log_policy_decision(result)
            return result

        rewritten_metadata = extract_metadata(reparsed, catalog.database_schema, findings)
        rewritten_metadata = replace(
            rewritten_metadata,
            effective_limit=limit_result.effective_limit,
            limit_was_added=limit_result.limit_was_added,
            limit_was_reduced=limit_result.limit_was_reduced,
        )
        result = SQLValidationResult(
            sql=rewritten_sql,
            original_sql=sql,
            valid=not has_error_findings(findings),
            metadata=rewritten_metadata,
            findings=tuple(findings),
        )
        log_policy_decision(result)
        return result


def invalid_result(sql: str, rule_name: str, code: str, message: str) -> SQLValidationResult:
    return SQLValidationResult(
        sql=sql,
        original_sql=sql,
        valid=False,
        metadata=SQLValidationMetadata(statement_type="unknown"),
        findings=(finding(rule_name, code, message),),
    )


def finding(rule_name: str, code: str, message: str) -> SQLValidationFinding:
    return SQLValidationFinding(code=code, message=message, rule_name=rule_name)


def has_error_findings(findings: list[SQLValidationFinding]) -> bool:
    return any(finding.severity == "error" for finding in findings)


def reparse_single_statement(sql: str) -> exp.Expression | None:
    try:
        statements = tuple(
            statement
            for statement in sqlglot.parse(
                sql,
                read=POSTGRES_DIALECT,
                error_level=ErrorLevel.RAISE,
            )
            if statement is not None
        )
    except ParseError:
        return None
    if len(statements) != 1:
        return None
    return statements[0]


def limit_rule(rules: tuple[GuardrailRule, ...]) -> LimitRule:
    for rule in rules:
        if isinstance(rule, LimitRule):
            return rule
    return LimitRule()


def log_policy_decision(result: SQLValidationResult) -> None:
    logger.info(
        "Generated SQL policy decision",
        extra={
            "valid": result.valid,
            "statement_type": result.metadata.statement_type,
            "finding_codes": [finding.code for finding in result.findings],
            "rule_names": [finding.rule_name for finding in result.findings],
            "referenced_tables": [
                table.identifier
                for table in result.metadata.referenced_tables
                if table.source == "table"
            ],
            "referenced_columns": [
                column.identifier
                for column in result.metadata.referenced_columns
                if column.table_identifier is not None
            ],
            "subquery_depth": result.metadata.subquery_depth,
            "effective_limit": result.metadata.effective_limit,
            "limit_was_added": result.metadata.limit_was_added,
            "limit_was_reduced": result.metadata.limit_was_reduced,
        },
    )


def classify_statement(statement: exp.Expression) -> SQLStatementType:
    if isinstance(statement, exp.Select):
        return "select"
    if isinstance(statement, exp.Insert):
        return "insert"
    if isinstance(statement, exp.Update):
        return "update"
    if isinstance(statement, exp.Delete):
        return "delete"
    if isinstance(statement, (exp.Create, exp.Drop, exp.Alter, exp.TruncateTable)):
        return "ddl"
    if isinstance(statement, (exp.Command, exp.Copy, exp.Grant)):
        return "command"
    return "unknown"


def unsafe_node_names(statement: exp.Expression) -> tuple[str, ...]:
    node_types = (
        exp.Insert,
        exp.Update,
        exp.Delete,
        exp.Merge,
        exp.Create,
        exp.Alter,
        exp.Drop,
        exp.TruncateTable,
        exp.Copy,
        exp.Grant,
        exp.Command,
        exp.Transaction,
        exp.Commit,
        exp.Rollback,
    )
    names: set[str] = set()
    for node_type in node_types:
        for node in statement.find_all(node_type):
            names.add(type(node).__name__)
    return tuple(sorted(names))


def literal_limit_value(limit: exp.Expression) -> int | None:
    expression = limit.args.get("expression")
    if not isinstance(expression, exp.Literal) or expression.args.get("is_string"):
        return None
    try:
        return int(str(expression.this))
    except ValueError:
        return None


def extract_metadata(
    statement: exp.Expression,
    database_schema: DatabaseSchema,
    findings: list[SQLValidationFinding],
) -> SQLValidationMetadata:
    catalog = catalog_lookup(database_schema)
    referenced_tables: list[ReferencedTable] = []
    referenced_columns: list[ReferencedColumn] = []
    aliases: set[str] = set()
    ctes = tuple(deduplicate(cte_alias(cte) for cte in statement.find_all(exp.CTE)))
    functions = tuple(
        sorted(
            deduplicate(
                function_name(function)
                for function in statement.find_all(exp.Func)
            )
        )
    )

    for scope in traverse_scope(statement):
        source_infos = source_infos_for_scope(scope, catalog, findings)
        for source in source_infos.values():
            if source.name:
                aliases.add(source.name)
            referenced_table = referenced_table_for_source(source)
            if referenced_table is not None:
                referenced_tables.append(referenced_table)

        for column in scope.columns:
            resolved = resolve_column(column, source_infos, findings)
            if resolved is not None:
                referenced_columns.append(resolved)

    aliases.update(
        alias
        for alias in (expression_alias(alias_node) for alias_node in statement.find_all(exp.Alias))
        if alias
    )

    return SQLValidationMetadata(
        statement_type=classify_statement(statement),
        referenced_tables=tuple(deduplicate_tables(referenced_tables)),
        referenced_columns=tuple(deduplicate_columns(referenced_columns)),
        aliases=tuple(sorted(aliases)),
        functions=functions,
        ctes=ctes,
        subquery_depth=max_subquery_depth(statement),
    )


def catalog_lookup(database_schema: DatabaseSchema) -> dict[str, CatalogTable]:
    return {
        table.identifier: CatalogTable(
            schema_name=table.schema_name,
            name=table.name,
            columns=frozenset(column.name for column in table.columns),
        )
        for table in database_schema.tables
    }


def source_infos_for_scope(
    scope: Scope,
    catalog: dict[str, CatalogTable],
    findings: list[SQLValidationFinding],
) -> dict[str, SourceInfo]:
    source_infos: dict[str, SourceInfo] = {}
    cte_source_names = set(scope.cte_sources)

    for source_name, (_node, source) in scope.selected_sources.items():
        if isinstance(source, exp.Table):
            normalized_source_name = table_alias_part(source) or normalize_name(source_name)
            table = resolve_table(source, catalog, findings)
            columns = table.columns if table is not None else frozenset()
            source_infos[normalized_source_name] = SourceInfo(
                name=normalized_source_name,
                source="table",
                columns=columns,
                table=table,
            )
        elif isinstance(source, Scope):
            normalized_source_name = (
                source_name if source_name in cte_source_names else normalize_name(source_name)
            )
            source_type: SQLReferenceSource = (
                "cte" if normalized_source_name in cte_source_names else "subquery"
            )
            source_infos[normalized_source_name] = SourceInfo(
                name=normalized_source_name,
                source=source_type,
                columns=selected_output_columns(source.expression),
            )

    return source_infos


def resolve_table(
    table: exp.Table,
    catalog: dict[str, CatalogTable],
    findings: list[SQLValidationFinding],
) -> CatalogTable | None:
    table_name = table_part(table)
    schema_name = schema_part(table)
    if not table_name:
        findings.append(
            finding(
                "SchemaReferenceRule",
                "unknown_table",
                "Generated SQL contains a table reference without a table name.",
            )
        )
        return None

    if schema_name is not None:
        identifier = f"{schema_name}.{table_name}"
        resolved = catalog.get(identifier)
        if resolved is None:
            findings.append(
                finding(
                    "SchemaReferenceRule",
                    "unknown_table",
                    f"Generated SQL references unknown table `{identifier}`.",
                )
            )
        return resolved

    matches = tuple(table for table in catalog.values() if table.name == table_name)
    if not matches:
        findings.append(
            finding(
                "SchemaReferenceRule",
                "unknown_table",
                f"Generated SQL references unknown table `{table_name}`.",
            )
        )
        return None
    if len(matches) > 1:
        findings.append(
            finding(
                "SchemaReferenceRule",
                "ambiguous_table",
                f"Generated SQL references ambiguous table `{table_name}`.",
            )
        )
        return None
    return matches[0]


def resolve_column(
    column: exp.Column,
    source_infos: dict[str, SourceInfo],
    findings: list[SQLValidationFinding],
) -> ReferencedColumn | None:
    column_name = column_part(column)
    source_name = column_source_part(column)
    schema_name = column_schema_part(column)

    if not column_name:
        findings.append(
            finding(
                "SchemaReferenceRule",
                "unknown_column",
                "Generated SQL contains a column reference without a column name.",
            )
        )
        return None

    if source_name is not None:
        source = source_infos.get(source_name)
        if source is None:
            findings.append(
                finding(
                    "SchemaReferenceRule",
                    "unknown_column_source",
                    f"Generated SQL references unknown column source `{source_name}`.",
                )
            )
            return None
        if schema_name is not None and source.table is not None:
            if source.table.schema_name != schema_name:
                findings.append(
                    finding(
                        "SchemaReferenceRule",
                        "unknown_column_source",
                        f"Generated SQL references unknown column source "
                        f"`{schema_name}.{source_name}`.",
                    )
                )
                return None
        return validate_column_in_source(column_name, source, findings)

    matching_sources = tuple(
        source for source in source_infos.values() if column_name in source.columns
    )
    if not matching_sources:
        findings.append(
            finding(
                "SchemaReferenceRule",
                "unknown_column",
                f"Generated SQL references unknown column `{column_name}`.",
            )
        )
        return None
    if len(matching_sources) > 1:
        findings.append(
            finding(
                "SchemaReferenceRule",
                "ambiguous_column",
                f"Generated SQL references ambiguous column `{column_name}`.",
            )
        )
        return None
    return referenced_column(column_name, matching_sources[0])


def validate_column_in_source(
    column_name: str,
    source: SourceInfo,
    findings: list[SQLValidationFinding],
) -> ReferencedColumn | None:
    if column_name not in source.columns:
        findings.append(
            finding(
                "SchemaReferenceRule",
                "unknown_column",
                f"Generated SQL references unknown column `{source.name}.{column_name}`.",
            )
        )
        return None
    return referenced_column(column_name, source)


def referenced_column(column_name: str, source: SourceInfo) -> ReferencedColumn:
    return ReferencedColumn(
        name=column_name,
        source_name=source.name,
        table_identifier=source.table_identifier,
        source=source.source,
    )


def referenced_table_for_source(source: SourceInfo) -> ReferencedTable | None:
    if source.source == "table":
        if source.table is None:
            return None
        return ReferencedTable(
            schema_name=source.table.schema_name,
            name=source.table.name,
            alias=source.name if source.name != source.table.name else None,
            source="table",
        )
    if source.source in {"cte", "subquery"}:
        return ReferencedTable(name=source.name, source=source.source)
    return None


def selected_output_columns(expression: exp.Expression) -> frozenset[str]:
    if not isinstance(expression, exp.Select):
        return frozenset()

    names: set[str] = set()
    for projection in expression.expressions:
        alias = expression_alias(projection)
        if alias:
            names.add(alias)
            continue
        if isinstance(projection, exp.Column):
            column_name = column_part(projection)
            if column_name:
                names.add(column_name)
    return frozenset(names)


def max_subquery_depth(expression: exp.Expression) -> int:
    return max_subquery_depth_inner(expression, 0)


def max_subquery_depth_inner(expression: exp.Expression, depth: int) -> int:
    max_depth = depth
    for child in expression.iter_expressions():
        child_depth = depth + 1 if isinstance(child, exp.Subquery) else depth
        max_depth = max(max_depth, max_subquery_depth_inner(child, child_depth))
    return max_depth


def function_name(function: exp.Func) -> str:
    sql_name = function.sql(dialect=POSTGRES_DIALECT).split("(", 1)[0]
    return sql_name.strip().lower()


def cte_alias(cte: exp.CTE) -> str:
    alias = cte.args.get("alias")
    if isinstance(alias, exp.TableAlias):
        return optional_identifier_part(alias.args.get("this")) or ""
    return normalize_name(cte.alias)


def expression_alias(expression: exp.Expression) -> str:
    alias = expression.alias
    if not alias:
        return ""
    return normalize_name(alias)


def table_part(table: exp.Table) -> str:
    return identifier_part(table.args.get("this"))


def schema_part(table: exp.Table) -> str | None:
    return optional_identifier_part(table.args.get("db"))


def table_alias_part(table: exp.Table) -> str | None:
    alias = table.args.get("alias")
    if not isinstance(alias, exp.TableAlias):
        return None
    return optional_identifier_part(alias.args.get("this"))


def column_part(column: exp.Column) -> str:
    return identifier_part(column.args.get("this"))


def column_source_part(column: exp.Column) -> str | None:
    return optional_identifier_part(column.args.get("table"))


def column_schema_part(column: exp.Column) -> str | None:
    return optional_identifier_part(column.args.get("db"))


def optional_identifier_part(value: object) -> str | None:
    if value is None:
        return None
    part = identifier_part(value)
    if not part:
        return None
    return part


def identifier_part(value: object) -> str:
    if isinstance(value, exp.Identifier):
        raw = str(value.this)
        if value.args.get("quoted"):
            return raw
        return raw.lower()
    if isinstance(value, str):
        return normalize_name(value)
    return ""


def normalize_name(value: str) -> str:
    return value.lower()


def deduplicate(values: Any) -> tuple[str, ...]:
    seen: set[str] = set()
    deduplicated: list[str] = []
    for value in values:
        if not is_nonempty_string(value) or value in seen:
            continue
        seen.add(value)
        deduplicated.append(value)
    return tuple(deduplicated)


def is_nonempty_string(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and bool(value)


def deduplicate_tables(tables: list[ReferencedTable]) -> tuple[ReferencedTable, ...]:
    seen: set[tuple[str, str | None, str | None, SQLReferenceSource]] = set()
    deduplicated: list[ReferencedTable] = []
    for table in tables:
        key = (table.name, table.schema_name, table.alias, table.source)
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(table)
    return tuple(deduplicated)


def deduplicate_columns(columns: list[ReferencedColumn]) -> tuple[ReferencedColumn, ...]:
    seen: set[tuple[str, str | None, str | None, SQLReferenceSource]] = set()
    deduplicated: list[ReferencedColumn] = []
    for column in columns:
        key = (column.name, column.source_name, column.table_identifier, column.source)
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(column)
    return tuple(deduplicated)
