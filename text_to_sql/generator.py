from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Generation:
    sql: str
    confidence: float
    rationale: str


def generate_sql(question, schema):
    normalized = _normalize(question)

    if "schema" in normalized or "table" in normalized:
        tables = ", ".join(sorted(schema.keys()))
        return Generation(
            "SELECT name AS table_name FROM sqlite_master WHERE type = 'table' ORDER BY name;",
            0.74,
            f"Question asks about available tables. Known tables: {tables}.",
        )

    if _has_any(normalized, "top", "highest", "largest", "most revenue", "best customer"):
        return Generation(
            """
SELECT
  c.name AS customer,
  ROUND(SUM(o.quantity * p.unit_price), 2) AS revenue
FROM orders o
JOIN customers c ON c.id = o.customer_id
JOIN products p ON p.id = o.product_id
WHERE o.status = 'paid'
GROUP BY c.id, c.name
ORDER BY revenue DESC
LIMIT 5;
""".strip(),
            0.88,
            "Ranks customers by paid order revenue.",
        )

    if _has_any(normalized, "region", "by region"):
        return Generation(
            """
SELECT
  c.region,
  COUNT(o.id) AS orders,
  ROUND(SUM(o.quantity * p.unit_price), 2) AS revenue
FROM customers c
JOIN orders o ON o.customer_id = c.id
JOIN products p ON p.id = o.product_id
WHERE o.status = 'paid'
GROUP BY c.region
ORDER BY revenue DESC;
""".strip(),
            0.84,
            "Aggregates paid orders by customer region.",
        )

    if _has_any(normalized, "product", "category", "products"):
        return Generation(
            """
SELECT
  p.category,
  p.name AS product,
  SUM(o.quantity) AS units_sold,
  ROUND(SUM(o.quantity * p.unit_price), 2) AS revenue
FROM products p
JOIN orders o ON o.product_id = p.id
WHERE o.status = 'paid'
GROUP BY p.id, p.category, p.name
ORDER BY revenue DESC;
""".strip(),
            0.82,
            "Reports units and revenue by product for paid orders.",
        )

    if _has_any(normalized, "revenue", "sales", "total"):
        return Generation(
            """
SELECT
  ROUND(SUM(o.quantity * p.unit_price), 2) AS total_revenue
FROM orders o
JOIN products p ON p.id = o.product_id
WHERE o.status = 'paid';
""".strip(),
            0.86,
            "Sums quantity times unit price for paid orders.",
        )

    if _has_any(normalized, "order", "orders", "recent"):
        return Generation(
            """
SELECT
  o.id,
  o.order_date,
  c.name AS customer,
  p.name AS product,
  o.quantity,
  o.status,
  ROUND(o.quantity * p.unit_price, 2) AS order_value
FROM orders o
JOIN customers c ON c.id = o.customer_id
JOIN products p ON p.id = o.product_id
ORDER BY o.order_date DESC
LIMIT 20;
""".strip(),
            0.78,
            "Lists recent orders with customer, product, status, and value.",
        )

    return Generation(
        """
SELECT
  c.name AS customer,
  c.region,
  COUNT(o.id) AS order_count,
  ROUND(COALESCE(SUM(o.quantity * p.unit_price), 0), 2) AS lifetime_value
FROM customers c
LEFT JOIN orders o ON o.customer_id = c.id
LEFT JOIN products p ON p.id = o.product_id
GROUP BY c.id, c.name, c.region
ORDER BY lifetime_value DESC;
""".strip(),
        0.52,
        "Fallback query summarizes customers because the question did not match a specific intent.",
    )


def _normalize(text):
    return re.sub(r"\s+", " ", text.lower()).strip()


def _has_any(text, *needles):
    return any(needle in text for needle in needles)
