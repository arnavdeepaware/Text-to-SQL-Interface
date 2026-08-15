const SQL_KEYWORDS = new Set([
  "as",
  "and",
  "by",
  "case",
  "desc",
  "else",
  "end",
  "from",
  "group",
  "having",
  "join",
  "left",
  "limit",
  "not",
  "null",
  "on",
  "or",
  "order",
  "outer",
  "select",
  "then",
  "where",
  "when",
  "with"
]);

const SQL_FUNCTIONS = new Set(["avg", "coalesce", "count", "max", "min", "sum"]);

export function SQLPreview({ sql }: { sql: string }) {
  return (
    <pre className="sql-preview" aria-label="Generated SQL">
      <code>
        {tokenizeSQL(sql).map((token, index) => (
          <span key={`${token.value}:${String(index)}`} className={`sql-token ${token.className}`}>
            {token.value}
          </span>
        ))}
      </code>
    </pre>
  );
}

interface SQLToken {
  value: string;
  className: string;
}

function tokenizeSQL(sql: string): SQLToken[] {
  return sql
    .split(/(\s+|'[^']*'|\b\d+(?:\.\d+)?\b|\b[a-zA-Z_][\w.]*\b|[(),;=*+-])/g)
    .map((value) => {
      const lower = value.toLowerCase();

      if (SQL_KEYWORDS.has(lower)) {
        return { value, className: "sql-token--keyword" };
      }

      if (SQL_FUNCTIONS.has(lower)) {
        return { value, className: "sql-token--function" };
      }

      if (/^'[^']*'$/.test(value)) {
        return { value, className: "sql-token--string" };
      }

      if (/^\d+(?:\.\d+)?$/.test(value)) {
        return { value, className: "sql-token--number" };
      }

      return { value, className: "sql-token--plain" };
    });
}
