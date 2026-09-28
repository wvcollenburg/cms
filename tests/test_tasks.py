"""Daily task runner (D17, D21): locking, the signed API, the fallback, Healthchecks pings."""
import hashlib
import hmac
import json
import time
from datetime import timedelta

import pytest
from click.testing import CliRunner
from freezegun import freeze_time

from app import tasks
from app.extensions import db
from app.models import TaskRun, User, utcnow
from app.public import cache

SECRET = "test-secret"


def _row(name):
    db.session.expire_all()
    return db.session.get(TaskRun, name)


def _signed(client, body=b"{}", ts=None, secret=SECRET):
    ts = str(int(time.time()) if ts is None else ts)
    sig = hmac.new(secret.encode(), ts.encode() + body, hashlib.sha256).hexdigest()
    return client.post("/api/tasks/run", data=body, content_type="application/json",
                       headers={"X-Task-Timestamp": ts, "X-Task-Signature": sig})


@pytest.fixture
def site(make_user, make_space, make_page):
    make_page("home")
    make_space("jan-hout", [make_user("jan")])


def test_cli_runs_all_tasks_and_records_them(app, site):
    result = CliRunner().invoke(app.cli, ["run-tasks"])
    assert result.exit_code == 0, result.output
    summary = json.loads(result.output)
    assert summary["ok"] and summary["trigger"] == "cli"
    assert summary["tasks"]["cache_rebuild"]["status"] == "ok"
    assert summary["tasks"]["cache_rebuild"]["count"] == 5  # / /en/ /makers /en/makers /jan-hout
    assert summary["tasks"]["demo_reset"] == {"status": "skipped", "reason": "off", "seconds": 0.0}
    assert cache.lookup("/jan-hout") is not None
    assert _row("daily").status == "ok" and _row("cache_rebuild").trigger == "cli"
    assert _row("demo_reset") is None  # skipped tasks leave no trace


def test_only_one_run_at_a_time(app, site):
    assert tasks.claim("cli", due_only=False)
    assert tasks.run("api") is None  # the lock is held
    assert CliRunner().invoke(app.cli, ["run-tasks"]).exit_code == 2


def test_a_crashed_run_is_taken_over(app, site):
    with freeze_time(utcnow() - timedelta(minutes=20)):
        assert tasks.claim("cli", due_only=False)  # ...and never finished
    assert tasks.run("api") is not None


def test_due_only_waits_a_day(app, site):
    assert tasks.run("cli")["ok"]
    assert not tasks.is_due()
    assert tasks.run("fallback", due_only=True) is None
    with freeze_time(utcnow() + timedelta(hours=24)):
        assert tasks.is_due()
        assert tasks.run("fallback", due_only=True)["trigger"] == "fallback"


def test_one_failing_task_does_not_stop_the_others(app, site, monkeypatch):
    def boom(trigger):
        raise RuntimeError("disk full")
    monkeypatch.setitem(tasks.TASKS, "demo_reset", boom)
    summary = tasks.run("cli")
    assert not summary["ok"]
    assert summary["tasks"]["demo_reset"]["status"] == "failed"
    assert "disk full" in summary["tasks"]["demo_reset"]["error"]
    assert summary["tasks"]["cache_rebuild"]["status"] == "ok"
    assert _row("daily").status == "failed" and _row("demo_reset").status == "failed"


def test_unknown_task_is_refused(app):
    with pytest.raises(ValueError):
        tasks.run("cli", ["make_coffee"])
    assert _row("daily") is None or _row("daily").status != "running"


# ------------------------------------------------------------------ API

def test_api_is_off_without_a_secret(app, client):
    assert _signed(client).status_code == 404


def test_api_checks_the_signature(app, client, site):
    app.config["TASK_SECRET"] = SECRET
    assert _signed(client, secret="wrong").status_code == 401
    assert _signed(client, ts=int(time.time()) - 600).status_code == 401  # replayed later
    assert client.post("/api/tasks/run", data="{}").status_code == 401     # unsigned
    body = b'{"tasks": ["cache_rebuild"]}'
    ts = str(int(time.time()))
    sig = hmac.new(SECRET.encode(), ts.encode() + b"{}", hashlib.sha256).hexdigest()
    tampered = client.post("/api/tasks/run", data=body, content_type="application/json",
                           headers={"X-Task-Timestamp": ts, "X-Task-Signature": sig})
    assert tampered.status_code == 401  # signature was for another body
    assert _row("daily") is None


def test_api_runs_tasks(app, client, site):
    app.config["TASK_SECRET"] = SECRET
    r = _signed(client, b'{"tasks": ["cache_rebuild"]}')
    assert r.status_code == 200 and r.json["ok"] and list(r.json["tasks"]) == ["cache_rebuild"]
    assert _row("daily").trigger == "api"
    assert _signed(client, b"").status_code == 200  # empty body: all tasks


def test_api_errors(app, client, site, monkeypatch):
    app.config["TASK_SECRET"] = SECRET
    assert _signed(client, b"not json").status_code == 400
    assert _signed(client, b'{"tasks": ["make_coffee"]}').status_code == 400
    monkeypatch.setitem(tasks.TASKS, "demo_reset", lambda t: 1 / 0)
    r = _signed(client)
    assert r.status_code == 500 and not r.json["ok"]  # curl -f in the caller exits non-zero
    tasks.claim("cli", due_only=False)
    assert _signed(client).status_code == 409


def test_api_needs_no_csrf_token(app, client, site):
    app.config.update(TASK_SECRET=SECRET, WTF_CSRF_ENABLED=True)
    assert _signed(client).status_code == 200


# ------------------------------------------------------------------ fallback

def test_fallback_runs_overdue_tasks_after_a_request(app, client, site):
    app.config["TASK_FALLBACK"] = True
    resp = client.get("/jan-hout")  # MISS: reaches Python
    assert resp.status_code == 200 and _row("daily") is None  # not before the response is out
    resp.close()  # what the server does once the response is sent (WSGI)
    assert _row("daily").trigger == "fallback" and _row("daily").status == "ok"
    started = _row("daily").last_started_at
    client.get("/makers").close()
    assert _row("daily").last_started_at == started  # ran today already


def test_fallback_skips_cached_pages_and_internal_requests(app, client, site):
    client.get("/jan-hout")  # fallback off: fills the cache
    app.config["TASK_FALLBACK"] = True
    hit = client.get("/jan-hout")
    hit.close()
    assert hit.headers["X-Page-Cache"] == "HIT" and _row("daily") is None
    tasks.task_cache_rebuild("cli")  # renders pages through the app itself
    assert _row("daily") is None


# ------------------------------------------------------------------ Healthchecks.io

def test_healthcheck_ping(app, site, monkeypatch):
    calls = []
    monkeypatch.setattr(tasks.urllib.request, "urlopen",
                        lambda req, timeout: calls.append(req.full_url) or type("R", (), {"close": lambda s: None})())
    tasks.run("cli")
    assert calls == []  # no URL configured
    app.config["HEALTHCHECK_URL"] = "https://hc-ping.com/abc"
    tasks.run("cli")
    monkeypatch.setitem(tasks.TASKS, "demo_reset", lambda t: 1 / 0)
    tasks.run("cli")
    assert calls == ["https://hc-ping.com/abc", "https://hc-ping.com/abc/fail"]


def test_a_failing_ping_does_not_fail_the_run(app, site, monkeypatch):
    app.config["HEALTHCHECK_URL"] = "https://hc-ping.com/abc"

    def offline(req, timeout):
        raise OSError("no network")
    monkeypatch.setattr(tasks.urllib.request, "urlopen", offline)
    assert tasks.run("cli")["ok"]


# ------------------------------------------------------------------ demo reset

def test_nightly_demo_reset_is_off_by_default(app):
    app.config["DEMO_MODE"] = True
    assert tasks.task_demo_reset("api")["reason"] == "off"


def test_nightly_demo_reset_runs_only_when_scheduled(app, make_user):
    app.config.update(DEMO_MODE=True, DEMO_NIGHTLY_RESET=True)
    make_user("tester")
    assert tasks.task_demo_reset("fallback")["status"] == "skipped"  # never during someone's visit
    summary = tasks.run("api")
    assert summary["ok"] and summary["tasks"]["demo_reset"]["status"] == "ok"
    db.session.expire_all()
    assert db.session.query(User).filter_by(email="tester@example.org").first() is None
    assert _row("daily").status == "ok" and not tasks.is_due()  # bookkeeping survived the reset


# ------------------------------------------------------------------ start page

def test_key_holder_sees_when_maintenance_last_ran(app, make_user, login):
    boss = make_user("boss", roles=("superadmin",), lang="en")
    c = login(boss)
    assert "has not run yet" in c.get("/beheer/").get_data(as_text=True)
    tasks.run("api")
    html = c.get("/beheer/").get_data(as_text=True)
    assert "last ran on" in html and "the daily call" in html and "more than 2 days" not in html
    with freeze_time(utcnow() + timedelta(hours=49)):
        assert "more than 2 days" in c.get("/beheer/").get_data(as_text=True)
    web = make_user("web", roles=("webmaster",), lang="en")
    assert "maintenance" not in login(web).get("/beheer/").get_data(as_text=True)
