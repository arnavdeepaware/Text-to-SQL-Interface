import sqlite3


FORBIDDEN_KEYWORDS = {
    "alter",
    "attach",
    "create",
    "delete",
    "detach",
    "drop",
    "insert",
    "pragma",
    "replace",
    "update",
    "vacuum",
}


class GuardrailError(ValueError):
    pass


def validate_readonly_sql(sql):
    statement = sql.strip()
    if not statement:
        raise GuardrailError("Generated SQL is empty.")
    if sqlite3.complete_statement(statement) and statement.count(";") > 1:
        raise GuardrailError("Only one SQL statement is allowed.")

    first_token = statement.split(None, 1)[0].lower()
    if first_token not in {"select", "with"}:
        raise GuardrailError("Only SELECT queries are allowed.")

    lowered = statement.lower()
    tokens = {token.strip("`\"'[](),;") for token in lowered.replace("\n", " ").split()}
    blocked = sorted(FORBIDDEN_KEYWORDS.intersection(tokens))
    if blocked:
        raise GuardrailError(f"Blocked unsafe SQL keyword: {blocked[0]}.")

    return True
