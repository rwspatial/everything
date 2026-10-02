"""Shared helpers: database connections and JSON-safe results."""
from __future__ import annotations

import datetime as dt
import decimal
import os
import re
import uuid
from typing import Any

import psycopg
from psycopg.rows import dict_row

# Qualified relation names the servers accept: schema.name, lowercase identifiers.
QUALIFIED = re.compile(r"^[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*$")
IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")
MAX_TEXT = 300


def connect() -> psycopg.Connection:
    """A read-only connection. The role enforces the same settings; these are belt and braces."""
    return psycopg.connect(
        os.environ["MCP_DATABASE_URL"],
        row_factory=dict_row,
        options="-c default_transaction_read_only=on -c statement_timeout=15000",
        application_name=os.environ.get("MCP_SERVER_NAME", "spatial-mcp"),
        connect_timeout=10,
    )


def jsonable(v: Any) -> Any:
    """Make one database value safe for a JSON tool result (long text, e.g. hex geometry, is shortened)."""
    if v is None or isinstance(v, (bool, int, float)):
        return v
    if isinstance(v, decimal.Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, (dt.date, dt.datetime, dt.time)):
        return v.isoformat()
    if isinstance(v, (bytes, memoryview)):
        v = bytes(v).hex()
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    if isinstance(v, dict):
        return {k: jsonable(x) for k, x in v.items()}
    s = str(v)
    if len(s) > MAX_TEXT:
        return s[:MAX_TEXT] + f"… ({len(s)} chars; for geometry select ST_AsText(geom) or ST_AsGeoJSON(geom))"
    return s


def first_line(e: Exception) -> str:
    return (str(e).strip().splitlines() or [type(e).__name__])[0]
