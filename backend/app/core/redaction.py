from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RedactionResult:
    value: str
    redacted: bool


SECRET_PATTERNS: tuple[tuple[re.Pattern[str], Callable[[re.Match[str]], str]], ...] = (
    (
        re.compile(r"\b(sk-[A-Za-z0-9_-]{12,})\b"),
        lambda match: "[REDACTED]",
    ),
    (
        re.compile(r"\b((?:api[_-]?key|token|secret|password)\s*[:=]\s*)[^\s,'\";]+", re.I),
        lambda match: f"{match.group(1)}[REDACTED]",
    ),
    (
        re.compile(r"\b(Bearer\s+)[A-Za-z0-9._~+/=-]{12,}\b", re.I),
        lambda match: f"{match.group(1)}[REDACTED]",
    ),
    (
        re.compile(r"\b([A-Za-z0-9+/]{32,}={0,2})\b"),
        lambda match: "[REDACTED]",
    ),
)


def redact_text(value: str) -> RedactionResult:
    redacted = False
    output = value
    for pattern, replacement in SECRET_PATTERNS:
        output, count = pattern.subn(replacement, output)
        redacted = redacted or count > 0
    return RedactionResult(value=output, redacted=redacted)


def redact_object(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value).value
    if isinstance(value, dict):
        return {
            str(key): redact_object(item)
            for key, item in value.items()
            if not key_looks_secret(str(key))
        }
    if isinstance(value, list | tuple):
        return [redact_object(item) for item in value]
    return value


def key_looks_secret(key: str) -> bool:
    normalized = key.lower()
    return any(marker in normalized for marker in ("api_key", "password", "secret", "token"))
