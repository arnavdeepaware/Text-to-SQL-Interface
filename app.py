from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlparse

from text_to_sql.database import ensure_database, get_schema, run_readonly_query
from text_to_sql.generator import generate_sql
from text_to_sql.guardrails import GuardrailError, validate_readonly_sql


ROOT = Path(__file__).parent
STATIC_DIR = ROOT / "static"
DB_PATH = ROOT / "data" / "demo.sqlite3"


class AppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/schema":
            self.send_json({"schema": get_schema(DB_PATH)})
            return
        if parsed.path == "/health":
            self.send_json({"status": "ok"})
            return
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/query":
            self.send_error(404, "Not found")
            return

        try:
            payload = self.read_json()
            question = str(payload.get("question", "")).strip()
            if not question:
                self.send_json({"error": "Question is required."}, status=400)
                return

            generation = generate_sql(question, get_schema(DB_PATH))
            validate_readonly_sql(generation.sql)
            rows, columns = run_readonly_query(DB_PATH, generation.sql)
            self.send_json(
                {
                    "question": question,
                    "sql": generation.sql,
                    "confidence": generation.confidence,
                    "rationale": generation.rationale,
                    "columns": columns,
                    "rows": rows,
                }
            )
        except GuardrailError as exc:
            self.send_json({"error": str(exc)}, status=400)
        except Exception as exc:
            self.send_json({"error": f"Query failed: {exc}"}, status=500)

    def read_json(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length).decode("utf-8")
        return json.loads(raw or "{}")

    def send_json(self, payload, status=200):
        encoded = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def main():
    ensure_database(DB_PATH)
    server = ThreadingHTTPServer(("127.0.0.1", 8000), AppHandler)
    print("Text-to-SQL Interface running at http://127.0.0.1:8000")
    server.serve_forever()


if __name__ == "__main__":
    main()
