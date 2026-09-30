"""Remove secrets from text before it is printed to a run log or stored in the database.

Two layers:
1. Exact values of every environment variable whose *name* looks secret (KEY, TOKEN, SECRET, PASSWORD).
2. Patterns that commonly carry credentials: `key=…`, `token=…` query parameters and Authorization headers.
"""
from __future__ import annotations

import os
import re

MASK = "•••"
_SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD)", re.I)
_QUERY = re.compile(
    r"(?i)\b(key|api[_-]?key|apikey|token|access[_-]?token|password|passwd|secret|signature|sig)=([^&\s\"'<>]+)"
)
_AUTH = re.compile(r"(?i)(authorization\s*[:=]\s*)(\S+(?:\s+[A-Za-z0-9._~+/=-]+)?)")


def secret_values() -> list[str]:
    """Current secret values, longest first (so overlapping values are masked whole)."""
    vals = {v for k, v in os.environ.items() if _SECRET_NAME.search(k) and v and len(v) >= 6}
    return sorted(vals, key=len, reverse=True)


def redact(text: str | None) -> str | None:
    if not text:
        return text
    for value in secret_values():
        text = text.replace(value, MASK)
    text = _QUERY.sub(lambda m: f"{m.group(1)}={MASK}", text)
    return _AUTH.sub(lambda m: f"{m.group(1)}{MASK}", text)
