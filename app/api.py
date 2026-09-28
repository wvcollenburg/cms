"""Task API (D21, §10a): `POST /api/tasks/run`, called once a day by a cron job elsewhere.

Auth: X-Task-Timestamp (unix seconds) and X-Task-Signature = hex HMAC-SHA256(TASK_SECRET,
timestamp + raw body). Rejected when the timestamp is more than 5 minutes off, so a captured
request can't be replayed later. deploy/call-tasks.sh is the matching caller.
"""
import hashlib
import hmac
import json
import time

from flask import Blueprint, abort, current_app, jsonify, request

from app import tasks

bp = Blueprint("api", __name__, url_prefix="/api")
MAX_SKEW = 300


def _check_signature() -> None:
    secret = current_app.config["TASK_SECRET"]
    if not secret:
        abort(404)
    ts = request.headers.get("X-Task-Timestamp", "")
    sig = request.headers.get("X-Task-Signature", "").strip().lower()
    if not ts.isdigit() or abs(time.time() - int(ts)) > MAX_SKEW:
        abort(401)
    expected = hmac.new(secret.encode(), ts.encode() + request.get_data(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        abort(401)


@bp.post("/tasks/run")
def run_tasks():
    _check_signature()
    raw = request.get_data()
    try:
        body = json.loads(raw) if raw.strip() else {}
        names = body.get("tasks") if isinstance(body, dict) else None
        if names is not None and not (isinstance(names, list) and all(isinstance(n, str) for n in names)):
            raise ValueError("tasks must be a list of names")
        summary = tasks.run("api", names or None)
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    if summary is None:
        return jsonify(ok=False, error="another run is still busy"), 409
    # A failed task answers 500, so the caller (curl -f) exits non-zero and its monitoring notices.
    return jsonify(summary), 200 if summary["ok"] else 500


@bp.errorhandler(401)
def unauthorized(e):
    return jsonify(ok=False, error="bad or expired signature"), 401
