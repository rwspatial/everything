#!/usr/bin/env python3
"""Dataset worker (admin plan Phase B): runs kind='dataset' jobs from app.jobs with scripts/geoimport.py.

  actions     import (cached download) | redownload | freshness | healthcheck | dry_run | set_enabled
  slots       per concurrency class: network (DATASET_SLOTS_NETWORK, 2), raster_heavy (1), db (1)
  claiming    FOR UPDATE SKIP LOCKED, so several workers can share the queue
  heartbeat   every 5 s; cancel_requested kills the child process group; the run is marked cancelled
  retries     failed import/redownload/freshness jobs are retried with exponential backoff
              (DATASET_RETRY_BASE seconds * 2^(attempt-1)) until max_attempts, then fail
  reaper      jobs whose worker stopped heartbeating are requeued (or failed after max_attempts)
  scheduler   every 5 min: freshness checks on each recipe's `freshness.every`, daily health checks, and
              re-downloads for recipes with `freshness.auto_refresh: true` when upstream changed

Runs in the geotools image as the loader role (service=loader), with the repository mounted at /work.
No Docker socket: it never touches containers. Start it with `make workers-up`.
"""
from __future__ import annotations

import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

REPO = Path(__file__).resolve().parent.parent
WORKER_ID = f"dataset@{socket.gethostname()}:{os.getpid()}"
SLOTS = {"network": int(os.environ.get("DATASET_SLOTS_NETWORK", "2")),
         "raster_heavy": int(os.environ.get("DATASET_SLOTS_RASTER", "1")),
         "db": int(os.environ.get("DATASET_SLOTS_DB", "1"))}
RETRY_BASE = float(os.environ.get("DATASET_RETRY_BASE", "30"))
RETRYABLE = {"import", "redownload", "freshness"}
STALE = 60
SCHEDULER = os.environ.get("DATASET_SCHEDULER", "on") != "off"
SCHEDULE_EVERY = 300
HEALTH_HOURS = float(os.environ.get("DATASET_HEALTH_HOURS", "24"))
ALIVE = Path("/tmp/dataset-worker-alive")
stop = threading.Event()
busy: dict[str, int] = {k: 0 for k in SLOTS}
lock = threading.Lock()


def log(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} {WORKER_ID}: {msg}", flush=True)


def connect():
    return psycopg.connect("service=loader", autocommit=True, row_factory=dict_row, application_name=WORKER_ID)


def argv_for(job: dict) -> list[str]:
    name, params, action = job["recipe_name"], job["params"] or {}, job["action"]
    commands = {"import": ["recipe", name], "redownload": ["recipe", name, "--redownload"],
                "freshness": ["freshness", name], "healthcheck": ["health", name], "dry_run": ["plan", name],
                "set_enabled": ["set-enabled", name, "true" if params.get("enabled") else "false"]}
    if action not in commands:
        raise ValueError(f"unknown dataset action {action!r}")
    return commands[action]


def claim(conn, classes: list[str]):
    return conn.execute(
        """UPDATE app.jobs j SET status = 'running', locked_by = %(w)s, locked_at = now(), heartbeat_at = now(),
                  started_at = now(), attempts = attempts + 1, progress_message = 'starting'
           WHERE j.id = (SELECT id FROM app.jobs WHERE kind = 'dataset' AND status = 'queued' AND run_after <= now()
                           AND concurrency_class = ANY(%(c)s) ORDER BY priority, id FOR UPDATE SKIP LOCKED LIMIT 1)
           RETURNING j.*""", {"w": WORKER_ID, "c": classes}).fetchone()


def reap(conn) -> None:
    for r in conn.execute(
            """UPDATE app.jobs SET
                      status = CASE WHEN status = 'cancel_requested' THEN 'cancelled'
                                    WHEN attempts < max_attempts THEN 'queued' ELSE 'failed' END,
                      locked_by = NULL,
                      finished_at = CASE WHEN status = 'cancel_requested' OR attempts >= max_attempts THEN now() END,
                      error = CASE WHEN status <> 'cancel_requested' AND attempts >= max_attempts
                                   THEN jsonb_build_object('message', 'worker stopped responding (no heartbeat)') ELSE error END
               WHERE kind = 'dataset' AND status IN ('running', 'cancel_requested')
                 AND coalesce(locked_by, '') NOT LIKE 'inline@%%'
                 AND heartbeat_at < now() - make_interval(secs => %s)
               RETURNING id, status""", (STALE,)).fetchall():
        conn.execute("UPDATE app.runs SET status = 'failed', finished_at = now(), error = 'worker stopped responding' "
                     "WHERE job_id = %s AND status = 'running'", (r["id"],))
        log(f"reaper: job {r['id']} -> {r['status']}")


def run_job(job: dict) -> None:
    jid, cls = job["id"], job["concurrency_class"]
    try:
        with connect() as conn:
            cmd = [sys.executable, "scripts/geoimport.py", *argv_for(job)]
            env = {**os.environ, "JOB_ID": str(jid), "TRIGGERED_BY": job["created_by"]}
            log(f"job {jid}: {' '.join(cmd[1:])}")
            child = subprocess.Popen(cmd, cwd=REPO, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, start_new_session=True)
            out: list[str] = []
            reader = threading.Thread(target=lambda: out.extend(child.stdout), daemon=True)
            reader.start()
            cancelled, last = False, 0.0
            while child.poll() is None:
                time.sleep(1)
                if time.monotonic() - last >= 5:
                    last = time.monotonic()
                    tail = "".join(out[-3:]).strip().splitlines()[-1:] if out else []
                    st = conn.execute("UPDATE app.jobs SET heartbeat_at = now(), progress_message = %s WHERE id = %s "
                                      "RETURNING status", ((tail[0][:200] if tail else "running"), jid)).fetchone()
                    if (st and st["status"] == "cancel_requested") or stop.is_set():
                        cancelled = True
                        os.killpg(child.pid, signal.SIGTERM)
                        try:
                            child.wait(15)
                        except subprocess.TimeoutExpired:
                            os.killpg(child.pid, signal.SIGKILL)
                        break
            reader.join(5)
            text = "".join(out)
            if cancelled:
                status = "queued" if stop.is_set() else "cancelled"
                conn.execute("UPDATE app.runs SET status = 'cancelled', finished_at = now(), log_tail = %s "
                             "WHERE job_id = %s AND status = 'running'", (text[-16000:], jid))
                conn.execute("UPDATE app.jobs SET status = %s, locked_by = NULL, finished_at = CASE WHEN %s = 'cancelled' "
                             "THEN now() END, progress_message = %s WHERE id = %s",
                             (status, status, "cancelled" if status == "cancelled" else "worker stopping; requeued", jid))
                log(f"job {jid}: {status}")
                return
            plan = next((l[5:] for l in reversed(out) if l.startswith("PLAN ")), None)
            if child.returncode == 0:
                result = {"plan": json.loads(plan)} if plan else None
                conn.execute("""UPDATE app.jobs SET status = 'succeeded', finished_at = now(), locked_by = NULL,
                                       progress_message = 'done', result = %s, error = NULL WHERE id = %s""",
                             (json.dumps(result) if result else None, jid))
                log(f"job {jid}: succeeded")
                if job["action"] in ("import", "redownload"):
                    # Re-check against upstream, so the dashboard's verdict reflects what we now hold.
                    enqueue(conn, job["recipe_name"], "freshness", "network", 3, by=f"after job {jid}")
                return
            message = failure_message(out, child.returncode)
            if job["action"] in RETRYABLE and job["attempts"] < job["max_attempts"]:
                delay = RETRY_BASE * 2 ** (job["attempts"] - 1)
                conn.execute("""UPDATE app.jobs SET status = 'queued', locked_by = NULL,
                                       run_after = now() + make_interval(secs => %s), progress_message = %s, error = %s
                                WHERE id = %s""",
                             (delay, f"attempt {job['attempts']} failed; retrying in {delay:g} s",
                              json.dumps({"message": message[:500]}), jid))
                log(f"job {jid}: attempt {job['attempts']}/{job['max_attempts']} failed ({message[:80]}); retry in {delay:g} s")
            else:
                conn.execute("""UPDATE app.jobs SET status = 'failed', finished_at = now(), locked_by = NULL,
                                       progress_message = 'failed', error = %s WHERE id = %s""",
                             (json.dumps({"message": message[:500], "log_tail": text[-4000:]}), jid))
                log(f"job {jid}: failed: {message[:120]}")
    except Exception as e:  # noqa: BLE001  never lose a slot
        log(f"job {jid}: worker error {e}")
    finally:
        with lock:
            busy[cls] -= 1


def failure_message(out: list[str], code: int) -> str:
    """The most useful line of a failed run: geoimport's ERROR line, else the exception line of a traceback."""
    lines = [l.strip() for l in out if l.strip()]
    for l in reversed(lines):
        if l.startswith("ERROR: "):
            return l[7:]
    for l in reversed(lines):
        if re.match(r"^[\w.]+(Error|Exception)\b", l):
            return l
    return lines[-1] if lines else f"exit code {code}"


# ---- scheduler -------------------------------------------------------------------------------------------------

def _every_seconds(every: str | None) -> float | None:
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([dhm])\s*", every or "")
    return float(m.group(1)) * {"d": 86400, "h": 3600, "m": 60}[m.group(2)] if m else None


def enqueue(conn, recipe: str, action: str, cls: str, max_attempts: int, params: dict | None = None,
            by: str = "scheduler") -> bool:
    key = f"{'import' if action in ('import', 'redownload') else action}:{recipe}"
    row = conn.execute(
        """INSERT INTO app.jobs (kind, recipe_name, action, params, concurrency_class, max_attempts, dedupe_key, created_by)
           VALUES ('dataset', %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (dedupe_key) WHERE status IN ('queued', 'running') AND dedupe_key IS NOT NULL DO NOTHING
           RETURNING id""", (recipe, action, json.dumps(params or {}), cls, max_attempts, key, by)).fetchone()
    return row is not None


def schedule(conn) -> None:
    recipes = conn.execute(
        """SELECT r.name, r.kind, r.freshness,
                  (SELECT max(checked_at) FROM app.freshness_checks f WHERE f.recipe_name = r.name) AS last_check,
                  (SELECT verdict FROM app.freshness_checks f WHERE f.recipe_name = r.name ORDER BY checked_at DESC LIMIT 1) AS verdict,
                  (SELECT max(started_at) FROM app.runs u WHERE u.recipe_name = r.name AND u.action = 'import'
                     AND u.status = 'succeeded') AS last_import,
                  (SELECT min(coalesce(health_checked_at, 'epoch')) FROM app.dataset_outputs o WHERE o.recipe_name = r.name) AS last_health
           FROM app.recipes r WHERE r.enabled AND r.yaml_path IS NOT NULL""").fetchall()
    queued = []
    now = time.time()
    for r in recipes:
        f = r["freshness"] or {}
        every = _every_seconds(f.get("every"))
        if f.get("method", "none") != "none" and every and (r["last_check"] is None or now - r["last_check"].timestamp() > every):
            if enqueue(conn, r["name"], "freshness", "network", 3):
                queued.append(f"freshness:{r['name']}")
        if (f.get("auto_refresh") and r["verdict"] == "stale" and r["last_check"]
                and (r["last_import"] is None or r["last_import"] < r["last_check"])):
            if enqueue(conn, r["name"], "redownload", "raster_heavy" if r["kind"] == "raster" else "network", 4):
                queued.append(f"redownload:{r['name']}")
        if r["last_health"] is not None and now - r["last_health"].timestamp() > HEALTH_HOURS * 3600:
            if enqueue(conn, r["name"], "healthcheck", "db", 1):
                queued.append(f"healthcheck:{r['name']}")
    if queued:
        log(f"scheduler queued {', '.join(queued)}")


def main() -> None:
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    log(f"slots {SLOTS}, retry base {RETRY_BASE:g} s, scheduler {'on' if SCHEDULER else 'off'}")
    last_maint = last_sched = 0.0
    while not stop.is_set():
        try:
            with connect() as conn:
                while not stop.is_set():
                    ALIVE.touch()
                    if time.monotonic() - last_maint > 30:
                        reap(conn)
                        last_maint = time.monotonic()
                    if SCHEDULER and time.monotonic() - last_sched > SCHEDULE_EVERY:
                        schedule(conn)
                        last_sched = time.monotonic()
                    with lock:
                        free = [c for c, n in SLOTS.items() if busy[c] < n]
                    job = claim(conn, free) if free else None
                    if job:
                        with lock:
                            busy[job["concurrency_class"]] += 1
                        threading.Thread(target=run_job, args=(job,), daemon=True).start()
                    else:
                        stop.wait(2)
        except psycopg.OperationalError as e:
            log(f"database unavailable ({str(e).strip().splitlines()[0]}); retrying in 5 s")
            stop.wait(5)
    log("stopping: running jobs are requeued")
    deadline = time.monotonic() + 20
    while any(busy.values()) and time.monotonic() < deadline:
        time.sleep(0.5)


if __name__ == "__main__":
    main()
