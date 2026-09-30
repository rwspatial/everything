"""Run history: every execution gets an app.jobs row (inline for the CLI) and an app.runs row.

    with RunRecorder("import", recipe="ne_lakes") as run:
        ...                        # anything printed (and child-process output via run_cmd) is captured
        run.rows = 1355

On exit the run is marked succeeded/failed/cancelled with a redacted log tail and error.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from collections import deque

import psycopg

from .redact import redact

LOG_TAIL_BYTES = 16_000

# The run currently being recorded in this process (read by geoimport.record for loaded_run_id).
ACTIVE: "RunRecorder | None" = None


def triggered_by() -> str:
    return os.environ.get("TRIGGERED_BY") or f"cli:{os.environ.get('USER', 'unknown')}"


class _Tee:
    """Writes to the real stream and keeps a bounded copy for the run log."""

    def __init__(self, stream, buf: deque, limit: int):
        self.stream, self.buf, self.limit, self.size = stream, buf, limit, 0

    def write(self, s: str) -> int:
        self.stream.write(s)
        self.buf.append(s)
        self.size += len(s)
        while self.size > self.limit * 4 and len(self.buf) > 1:
            self.size -= len(self.buf.popleft())
        return len(s)

    def flush(self):
        self.stream.flush()

    def isatty(self):
        return self.stream.isatty()

    def __getattr__(self, name):
        return getattr(self.stream, name)


def run_cmd(cmd: list[str]) -> int:
    """Run a child process, streaming its combined output through sys.stdout (so it is captured)."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert proc.stdout is not None
    while chunk := proc.stdout.read1(4096) if hasattr(proc.stdout, "read1") else proc.stdout.read(4096):
        sys.stdout.write(chunk.decode(errors="replace"))
        sys.stdout.flush()
    return proc.wait()


class RunRecorder:
    def __init__(self, action: str, recipe: str | None = None, params: dict | None = None,
                 conninfo: str = "service=loader", concurrency: str = "network"):
        self.action, self.recipe, self.params = action, recipe, params or {}
        self.conninfo, self.concurrency = conninfo, concurrency
        self.rows: int | None = None
        self.bytes: int | None = None
        self.outcome: str | None = None
        self.report: dict = {}
        self.run_id: int | None = None
        self.job_id: int | None = None
        self._buf: deque[str] = deque()

    def __enter__(self) -> "RunRecorder":
        self.conn = psycopg.connect(self.conninfo, autocommit=True)
        who, host = triggered_by(), socket.gethostname()
        self.job_id = self.conn.execute(
            """INSERT INTO app.jobs (recipe_name, action, params, concurrency_class, status, attempts,
                                     locked_by, locked_at, heartbeat_at, created_by)
               VALUES (%s, %s, %s, %s, 'running', 1, %s, now(), now(), %s) RETURNING id""",
            (self.recipe, self.action, json.dumps(self.params), self.concurrency, f"inline@{host}", who),
        ).fetchone()[0]
        self.run_id = self.conn.execute(
            """INSERT INTO app.runs (job_id, recipe_name, action, params, status, triggered_by, host, started_at)
               VALUES (%s, %s, %s, %s, 'running', %s, %s, now()) RETURNING id""",
            (self.job_id, self.recipe, self.action, json.dumps(self.params), who, host),
        ).fetchone()[0]
        self._out, self._err = sys.stdout, sys.stderr
        sys.stdout = _Tee(self._out, self._buf, LOG_TAIL_BYTES)
        sys.stderr = _Tee(self._err, self._buf, LOG_TAIL_BYTES)
        global ACTIVE
        ACTIVE = self
        return self

    def log_tail(self) -> str:
        return redact("".join(self._buf)[-LOG_TAIL_BYTES:]) or ""

    def __exit__(self, exc_type, exc, tb) -> bool:
        global ACTIVE
        ACTIVE = None
        sys.stdout.flush()
        sys.stdout, sys.stderr = self._out, self._err
        if exc_type is None:
            status = "succeeded"
        elif issubclass(exc_type, KeyboardInterrupt):
            status = "cancelled"
        else:
            status = "failed"
        error = redact(f"{exc_type.__name__ if exc_type else ''}: {exc}".strip(": ")) if exc else None
        try:
            self.conn.execute(
                """UPDATE app.runs SET status = %s, finished_at = now(), error = %s, log_tail = %s,
                          rows_written = %s, bytes_downloaded = %s, outcome = %s, report = %s
                   WHERE id = %s""",
                (status, error, self.log_tail(), self.rows, self.bytes, self.outcome,
                 json.dumps(self.report), self.run_id),
            )
            self.conn.execute(
                "UPDATE app.jobs SET status = %s, finished_at = now(), heartbeat_at = now() WHERE id = %s",
                (status, self.job_id),
            )
        finally:
            self.conn.close()
        return False  # never swallow the exception
