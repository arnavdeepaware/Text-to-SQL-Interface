from __future__ import annotations

import json
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = "http://frontend:8080"
SAFE_REQUEST_ID = "full-stack-safe-query"
UNSAFE_REQUEST_ID = "full-stack-unsafe-query"


def request_json(
    path: str,
    method: str = "GET",
    payload: dict[str, object] | None = None,
    request_id: str = SAFE_REQUEST_ID,
) -> tuple[int, dict[str, Any]]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        f"{BASE_URL}{path}",
        data=body,
        method=method,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Request-ID": request_id,
        },
    )
    try:
        with urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))
    except URLError as error:
        raise RuntimeError(f"unable to reach {path}: {error.reason}") from error


def assert_full_stack() -> None:
    with urlopen(f"{BASE_URL}/", timeout=10) as response:
        if response.status != 200 or b"<div id=\"root\">" not in response.read():
            raise RuntimeError("frontend did not serve the React application")

    health_status, health = request_json("/health")
    if health_status != 200 or health.get("status") != "ok":
        raise RuntimeError(f"backend health through frontend proxy failed: {health}")

    safe_status, safe = request_json(
        "/v1/query",
        method="POST",
        payload={"question": "List cancelled orders for the demo smoke test"},
        request_id=SAFE_REQUEST_ID,
    )
    rows = safe.get("rows", [])
    if (
        safe_status != 200
        or safe.get("result_type") != "query_result"
        or not str(safe.get("sql", "")).startswith("SELECT order_number, status")
        or [row.get("order_number") for row in rows] != ["ORD-1003", "ORD-1009"]
        or safe.get("metadata", {}).get("telemetry", {}).get("provider_name") != "fake"
    ):
        raise RuntimeError(f"safe query did not return the deterministic result: {safe}")

    unsafe_status, unsafe = request_json(
        "/v1/query",
        method="POST",
        payload={"question": "Show cancelled orders for the unsafe smoke test"},
        request_id=UNSAFE_REQUEST_ID,
    )
    if unsafe_status != 502 or unsafe.get("error", {}).get("code") != "sql_validation_failed":
        raise RuntimeError(f"unsafe query was not blocked by guardrails: {unsafe}")

    print("Full-stack smoke test passed.")


def main() -> int:
    try:
        assert_full_stack()
    except (RuntimeError, ValueError, KeyError) as error:
        print(f"Full-stack smoke test failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
