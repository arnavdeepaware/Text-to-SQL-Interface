import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  region TEXT NOT NULL,
  signup_date TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  category TEXT NOT NULL,
  unit_price REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY,
  customer_id INTEGER NOT NULL,
  product_id INTEGER NOT NULL,
  order_date TEXT NOT NULL,
  quantity INTEGER NOT NULL,
  status TEXT NOT NULL,
  FOREIGN KEY (customer_id) REFERENCES customers(id),
  FOREIGN KEY (product_id) REFERENCES products(id)
);
"""

SEED = {
    "customers": [
        (1, "Acme Studios", "West", "2025-01-17"),
        (2, "Northstar Labs", "Northeast", "2025-02-04"),
        (3, "Canyon Retail", "Southwest", "2025-03-21"),
        (4, "Bluebird Health", "Midwest", "2025-04-09"),
        (5, "Harbor Foods", "Southeast", "2025-05-12"),
    ],
    "products": [
        (1, "Analytics Pro", "Software", 129.0),
        (2, "Data Cleanse", "Software", 79.0),
        (3, "Support Retainer", "Services", 499.0),
        (4, "Onboarding", "Services", 899.0),
    ],
    "orders": [
        (1, 1, 1, "2026-01-12", 4, "paid"),
        (2, 1, 3, "2026-02-02", 1, "paid"),
        (3, 2, 2, "2026-02-15", 8, "paid"),
        (4, 3, 4, "2026-03-08", 1, "refunded"),
        (5, 4, 1, "2026-03-19", 2, "paid"),
        (6, 5, 3, "2026-04-03", 2, "pending"),
        (7, 2, 1, "2026-04-22", 5, "paid"),
        (8, 3, 2, "2026-05-07", 3, "paid"),
    ],
}


def connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_database(db_path):
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as conn:
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0:
            conn.executemany("INSERT INTO customers VALUES (?, ?, ?, ?)", SEED["customers"])
            conn.executemany("INSERT INTO products VALUES (?, ?, ?, ?)", SEED["products"])
            conn.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?)", SEED["orders"])


def get_schema(db_path):
    ensure_database(db_path)
    with connect(db_path) as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()
        schema = {}
        for table in tables:
            name = table["name"]
            columns = conn.execute(f"PRAGMA table_info({name})").fetchall()
            schema[name] = [
                {"name": col["name"], "type": col["type"], "primaryKey": bool(col["pk"])}
                for col in columns
            ]
        return schema


def run_readonly_query(db_path, sql):
    ensure_database(db_path)
    with connect(db_path) as conn:
        conn.execute("PRAGMA query_only = ON")
        cursor = conn.execute(sql)
        rows = [dict(row) for row in cursor.fetchall()]
        columns = [description[0] for description in cursor.description or []]
        return rows, columns
