"""Daily task runner (D17, D21, §10a): one idempotent run of all periodic jobs.

Triggers:
- `POST /api/tasks/run`, HMAC-signed, called once a day by a cron job on William's server
  (deploy/call-tasks.sh). This is the primary trigger: STRATO Basic has no cron.
- `flask run-tasks`, by hand or from cron on Profile A.
- Fallback: a normal request notices the last run is over a day old and runs it after the
  response has been sent. Cached pages never reach Python, so this is only the safety net.

The `daily` row in task_runs is the lock: an atomic UPDATE claims it, so the API, the CLI and
the fallback never run at the same time. Every task has its own row with its last result.
After every run, Healthchecks.io gets a ping (or /fail), so a run that *doesn't* happen is
noticed too: the missing ping triggers the alert (§10a, dead man's switch).
"""
import json
import time
import urllib.request
from datetime import timedelta

from flask import current_app
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import TaskRun, utcnow

LOCK = "daily"
DUE_AFTER = timedelta(hours=23)       # the fallback runs when the last start is older than this
STALE_AFTER = timedelta(minutes=15)   # a "running" claim older than this crashed; take it over
SCHEDULED = ("api", "cli")            # triggers that run at a known quiet time (not a visitor)
INTERNAL = "createur.internal"        # WSGI environ flag: a request the app makes to itself


# ------------------------------------------------------------------ the tasks

def task_demo_reset(trigger: str) -> dict:
    """Demo only, and off unless DEMO_NIGHTLY_RESET=1: put the demo content back every night."""
    cfg = current_app.config
    if not (cfg["DEMO_MODE"] and cfg["DEMO_NIGHTLY_RESET"]):
        return {"status": "skipped", "reason": "off"}
    if trigger not in SCHEDULED:
        return {"status": "skipped", "reason": "only at night, not during a visit"}
    from app.cli import reset_demo
    reset_demo()
    return {"status": "ok", "count": 1}


def task_cache_rebuild(trigger: str) -> dict:
    """Render every public page into the static cache, so visitors never wait for Python."""
    if not current_app.config["PAGE_CACHE"]:
        return {"status": "skipped", "reason": "page cache off"}
    from app.public import cache
    client = current_app.test_client()
    count = 0
    for url in cache.public_urls():
        resp = client.get(url, environ_base={INTERNAL: True})
        count += resp.headers.get("X-Page-Cache") in ("MISS", "HIT")
    return {"status": "ok", "count": count}


# In order: a demo reset clears the cache, so the rebuild runs after it.
# The purge, tombstone expiry and purge reminders join here after the opening (§11).
TASKS = {
    "demo_reset": task_demo_reset,
    "cache_rebuild": task_cache_rebuild,
}


# ------------------------------------------------------------------ locking

def _ensure_row(task: str) -> None:
    if db.session.get(TaskRun, task) is None:
        db.session.add(TaskRun(task=task, status="never"))
        try:
            db.session.commit()
        except IntegrityError:  # another process created it at the same moment
            db.session.rollback()


def claim(trigger: str, *, due_only: bool) -> bool:
    """Atomically take the `daily` lock. With due_only, only when the last start is a day old."""
    _ensure_row(LOCK)
    now = utcnow()
    cond = [TaskRun.task == LOCK,
            or_(TaskRun.status != "running", TaskRun.last_started_at < now - STALE_AFTER)]
    if due_only:
        cond.append(or_(TaskRun.last_started_at.is_(None), TaskRun.last_started_at < now - DUE_AFTER))
    result = db.session.execute(
        update(TaskRun).where(*cond).values(status="running", last_started_at=now, trigger=trigger)
        .execution_options(synchronize_session=False)
    )
    db.session.commit()
    return result.rowcount == 1


def is_due() -> bool:
    row = db.session.get(TaskRun, LOCK)
    if row is None or row.last_started_at is None:
        return True
    return row.last_started_at < utcnow() - DUE_AFTER and not (
        row.status == "running" and row.last_started_at > utcnow() - STALE_AFTER)


def _record(task: str, status: str, trigger: str, started) -> None:
    # A demo reset drops and recreates every table, task_runs included: recreate the row.
    _ensure_row(task)
    row = db.session.get(TaskRun, task)
    row.status, row.trigger, row.last_finished_at = status, trigger, utcnow()
    row.last_started_at = started
    db.session.commit()


# ------------------------------------------------------------------ running

def run(trigger: str, names: list[str] | None = None, *, due_only: bool = False) -> dict | None:
    """Run the tasks (all of them, or `names`). Returns None when another run holds the lock."""
    unknown = set(names or ()) - set(TASKS)
    if unknown:
        raise ValueError(f"unknown task(s): {', '.join(sorted(unknown))}")
    if not claim(trigger, due_only=due_only):
        return None
    started = utcnow()
    results = {}
    for name, fn in TASKS.items():
        if names and name not in names:
            continue
        t0, task_started = time.monotonic(), utcnow()
        try:
            res = fn(trigger)
        except Exception as exc:  # one failing task must not stop the others
            db.session.rollback()
            current_app.logger.exception("task %s failed", name)
            res = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"[:300]}
        res["seconds"] = round(time.monotonic() - t0, 2)
        results[name] = res
        if res["status"] != "skipped":
            _record(name, res["status"], trigger, task_started)
    ok = all(r["status"] != "failed" for r in results.values())
    _record(LOCK, "ok" if ok else "failed", trigger, started)
    summary = {"ok": ok, "trigger": trigger, "tasks": results}
    _ping(summary)
    return summary


def _ping(summary: dict) -> None:
    """Healthchecks.io: a ping per run, /fail with the summary when something failed."""
    url = current_app.config["HEALTHCHECK_URL"]
    if not url:
        return
    if not summary["ok"]:
        url = url.rstrip("/") + "/fail"
    try:
        req = urllib.request.Request(url, data=json.dumps(summary).encode(), method="POST")
        urllib.request.urlopen(req, timeout=10).close()
    except Exception:  # monitoring must never break the run; the missing ping is the alert
        current_app.logger.warning("healthcheck ping failed", exc_info=True)


def last_run() -> TaskRun | None:
    return db.session.scalar(select(TaskRun).where(TaskRun.task == LOCK))
