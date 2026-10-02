"""Claim loop for analysis jobs (plan §5.3).

  queued -> running -> succeeded | failed | cancelled
  - claim with FOR UPDATE SKIP LOCKED (several workers can run side by side: docker compose up --scale worker=2)
  - each job runs in a child process (Python module or Rscript); heartbeat every 5 s; cancel_requested and the
    descriptor's timeoutSec kill the child
  - a reaper requeues jobs whose worker stopped heartbeating (or fails them after max_attempts)
  - on success: app.publish_job_layer -> wait until tiPG serves the view -> result = {layerSpec, report, ...}
"""
from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from .registry import HOME, discover

sys.path.insert(0, str(HOME / "contracts"))
import validate as V  # noqa: E402  contracts/validate.py: the job's LayerSpec must satisfy the manifest contract

DB = os.environ["WORKER_DATABASE_URL"]
TIPG = os.environ.get("TIPG_URL", "http://tipg:8000")
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
HEARTBEAT = 5
STALE = 60          # seconds without a heartbeat before the reaper steps in
TIPG_TTL = int(os.environ.get("TIPG_CATALOG_TTL", "300"))
TIPG_WAIT = int(os.environ.get("TIPG_WAIT_SECONDS", "360"))  # > TIPG_CATALOG_TTL
ALIVE = Path("/tmp/worker-alive")
stop = threading.Event()


def log(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} worker {WORKER_ID}: {msg}", flush=True)


def connect():
    return psycopg.connect(DB, autocommit=True, row_factory=dict_row, application_name=f"worker {WORKER_ID}")


def register(conn, processes) -> None:
    for p in processes.values():
        d = p.descriptor
        conn.execute(
            """INSERT INTO app.processes (id, runtime, version, title, description, descriptor, registered_by)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (id) DO UPDATE SET runtime = EXCLUDED.runtime, version = EXCLUDED.version,
                   title = EXCLUDED.title, description = EXCLUDED.description, descriptor = EXCLUDED.descriptor,
                   registered_by = EXCLUDED.registered_by, last_seen_at = now()""",
            (d["id"], d["runtime"], d["version"], d["title"], d.get("description"), json.dumps(d), WORKER_ID))
    log(f"registered {', '.join(sorted(processes))}")


def reap(conn) -> None:
    """Jobs whose worker stopped heartbeating: cancellations finish, others are retried until max_attempts."""
    rows = conn.execute(
        """UPDATE app.jobs SET
                  status = CASE WHEN status = 'cancel_requested' THEN 'cancelled'
                                WHEN attempts < max_attempts THEN 'queued' ELSE 'failed' END,
                  locked_by = NULL,
                  finished_at = CASE WHEN status = 'cancel_requested' OR attempts >= max_attempts THEN now() END,
                  error = CASE WHEN status <> 'cancel_requested' AND attempts >= max_attempts
                               THEN jsonb_build_object('message', 'worker stopped responding (no heartbeat)') ELSE error END
           WHERE kind = 'process' AND status IN ('running', 'cancel_requested')
             AND heartbeat_at < now() - make_interval(secs => %s)
           RETURNING id, status""", (STALE,)).fetchall()
    for r in rows:
        log(f"reaper: job {r['id']} -> {r['status']}")


def claim(conn, process_ids: list[str]):
    return conn.execute(
        """UPDATE app.jobs j SET status = 'running', locked_by = %(w)s, locked_at = now(), heartbeat_at = now(),
                  started_at = now(), attempts = attempts + 1, progress = 0, progress_message = 'starting', error = NULL
           WHERE j.id = (SELECT id FROM app.jobs WHERE kind = 'process' AND status = 'queued' AND run_after <= now()
                           AND process_id = ANY(%(p)s) ORDER BY priority, id FOR UPDATE SKIP LOCKED LIMIT 1)
           RETURNING j.*""", {"w": WORKER_ID, "p": process_ids}).fetchone()


def tipg_serves(collection: str) -> bool:
    try:
        with urllib.request.urlopen(f"{TIPG}/collections/{collection}", timeout=10) as r:
            return r.status == 200
    except (urllib.error.URLError, TimeoutError):
        return False


def layer_spec(job: dict, proc, collection: str, out: dict) -> dict:
    d = proc.descriptor
    title = out.get("title") or f"{d['title']} (job {job['id']})"
    spec = {"id": f"job-{job['id']}", "title": title, "group": "Analysis results",
            "source": {"type": "tipg-vector", "collection": collection,
                       **({"properties": out["properties"]} if out.get("properties") else {})},
            "style": out["style"], "legend": out["legend"],
            "interaction": {**({"popup": {"template": out["popup"]}} if out.get("popup") else {}), "inspect": True},
            "attribution": f"Analysis: {d['id']} {d['version']}"}
    # The LayerSpec must satisfy the same contract as hand-written layers.
    probe = {"manifestVersion": 1, "slug": "job-check", "title": "check", "status": "draft",
             "view": {"center": [-69.25, 45.3], "zoom": 6.3}, "layers": [spec]}
    errors = [i for i in V.validate_schema(probe) + V.validate_rules(probe) if i.level == "error"]
    if errors:
        raise RuntimeError("the process returned an invalid layer: " + "; ".join(f"{e.code} {e.path}: {e.message}" for e in errors))
    return spec


def run_job(conn, job: dict, proc) -> None:
    jid = job["id"]
    env = {**os.environ, "JOB_ID": str(jid), "JOB_INPUTS": json.dumps(job["inputs"] or {}),
           "OUT_TABLE": f"ml_out.job_{jid}", "WORKER_HOME": str(HOME)}
    cmd = ([sys.executable, "-m", "worker.child", proc.python_module] if proc.python_module
           else ["Rscript", "--vanilla", str(proc.r_script)])
    log(f"job {jid}: {proc.id} {json.dumps(job['inputs'])}")
    child = subprocess.Popen(cmd, cwd=HOME, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             start_new_session=True)
    output: list[str] = []
    reader = threading.Thread(target=lambda: output.extend(child.stdout), daemon=True)
    reader.start()
    started, last_beat, outcome = time.monotonic(), 0.0, None
    while child.poll() is None:
        time.sleep(1)
        if time.monotonic() - last_beat >= HEARTBEAT:
            last_beat = time.monotonic()
            st = conn.execute("UPDATE app.jobs SET heartbeat_at = now() WHERE id = %s RETURNING status", (jid,)).fetchone()
            ALIVE.touch()
            if st and st["status"] == "cancel_requested":
                outcome = "cancelled"
        if time.monotonic() - started > proc.timeout:
            outcome = "timeout"
        if outcome or stop.is_set():
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
            break
    reader.join(5)
    tail = "".join(output)[-4000:]
    if outcome == "cancelled" or (stop.is_set() and outcome is None):
        conn.execute("SELECT app.discard_job_output(%s)", (jid,))
        status = "cancelled" if outcome == "cancelled" else "queued"
        conn.execute("UPDATE app.jobs SET status = %s, locked_by = NULL, finished_at = CASE WHEN %s = 'cancelled' "
                     "THEN now() END, progress_message = %s WHERE id = %s",
                     (status, status, "cancelled" if status == "cancelled" else "worker stopping; requeued", jid))
        log(f"job {jid}: {status}")
        return
    result_line = next((l for l in reversed(output) if l.startswith("RESULT ")), None)
    try:
        if outcome == "timeout":
            raise RuntimeError(f"timed out after {proc.timeout} s")
        if child.returncode != 0 or not result_line:
            raise RuntimeError(f"process exited with code {child.returncode}")
        out = json.loads(result_line[len("RESULT "):])
        conn.execute("UPDATE app.jobs SET progress = 0.95, progress_message = 'publishing' WHERE id = %s", (jid,))
        collection = conn.execute("SELECT app.publish_job_layer(%s) AS c", (jid,)).fetchone()["c"]
        spec = layer_spec(job, proc, collection, out)
        # Each tiPG process refreshes its catalog lazily, on its first request after TIPG_CATALOG_TTL. Once one TTL
        # has passed since publishing, every process picks the view up on its next request, so wait that long
        # (and until tiPG answers) before calling the layer served.
        published = time.monotonic()
        deadline = published + max(TIPG_WAIT, TIPG_TTL + 30)
        while time.monotonic() < published + TIPG_TTL + 1 or not tipg_serves(collection):
            if time.monotonic() > deadline:
                raise RuntimeError(f"tiPG did not list {collection} within {TIPG_WAIT} s (TIPG_CATALOG_TTL?)")
            conn.execute("UPDATE app.jobs SET heartbeat_at = now(), progress_message = 'waiting for tiPG' WHERE id = %s", (jid,))
            ALIVE.touch()
            time.sleep(3)
        result = {"collection": collection, "layerSpec": spec, "report": out.get("report", {}),
                  "rows": out.get("rows"), "process": {"id": proc.id, "version": proc.descriptor["version"]}}
        conn.execute("""UPDATE app.jobs SET status = 'succeeded', progress = 1, progress_message = 'done', result = %s,
                               finished_at = now(), locked_by = NULL WHERE id = %s""", (json.dumps(result), jid))
        log(f"job {jid}: succeeded -> {collection} ({out.get('rows')} rows)")
    except Exception as e:  # noqa: BLE001  any failure ends the job with its message and the child's output
        conn.execute("SELECT app.discard_job_output(%s)", (jid,))
        conn.execute("""UPDATE app.jobs SET status = 'failed', finished_at = now(), locked_by = NULL, error = %s
                        WHERE id = %s""", (json.dumps({"message": str(e)[:500], "log_tail": tail}), jid))
        log(f"job {jid}: failed: {e}")


def main() -> None:
    processes = discover()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    while not stop.is_set():
        try:
            with connect() as conn:
                register(conn, processes)
                last_seen = 0.0
                while not stop.is_set():
                    ALIVE.touch()
                    if time.monotonic() - last_seen > 30:
                        conn.execute("UPDATE app.processes SET last_seen_at = now() WHERE id = ANY(%s)", (list(processes),))
                        reap(conn)
                        last_seen = time.monotonic()
                    job = claim(conn, list(processes))
                    if job:
                        run_job(conn, job, processes[job["process_id"]])
                    else:
                        stop.wait(2)
        except psycopg.OperationalError as e:
            log(f"database unavailable ({str(e).strip().splitlines()[0]}); retrying in 5 s")
            stop.wait(5)
    log("stopped")


if __name__ == "__main__":
    main()
