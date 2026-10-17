"""STRATO deploy pieces (§10a): the CGI wrapper, the .htaccess cache mapping, create-superadmin."""
import os
import re
import subprocess
import sys
from pathlib import Path

from click.testing import CliRunner

from app.extensions import db
from app.models import User

REPO = Path(__file__).resolve().parent.parent
STRATO = REPO / "deploy" / "strato"


def test_create_superadmin_creates_then_promotes(app, make_user):
    run = CliRunner().invoke
    result = run(app.cli, ["create-superadmin", " New@Example.org ", "Nieuwe Sleutelhouder"])
    assert result.exit_code == 0, result.output
    with app.app_context():
        user = db.session.query(User).filter_by(email="new@example.org").one()
        assert user.is_superadmin and user.display_name == "Nieuwe Sleutelhouder"

    make_user("maartje", roles=("webmaster",))
    assert run(app.cli, ["create-superadmin", "maartje@example.org", "x"]).exit_code == 0
    with app.app_context():
        user = db.session.query(User).filter_by(email="maartje@example.org").one()
        assert user.is_superadmin and user.is_webmaster and user.display_name == "Maartje"
    assert "already" in run(app.cli, ["create-superadmin", "maartje@example.org", "x"]).output


def test_create_superadmin_refuses_a_deactivated_user(app, make_user):
    make_user("weg", active=False)
    result = CliRunner().invoke(app.cli, ["create-superadmin", "weg@example.org", "Weg"])
    assert result.exit_code != 0
    with app.app_context():
        assert not db.session.query(User).filter_by(email="weg@example.org").one().is_superadmin


def _cgi(tmp_path, uri, env_lines):
    private = tmp_path / "private"
    private.mkdir(exist_ok=True)
    (private / ".env").write_text("\n".join(env_lines) + "\n")
    script = tmp_path / "createur.cgi"
    script.write_text((STRATO / "createur.cgi").read_text()
                      .replace("@PYTHON@", sys.executable)
                      .replace("@APP_DIR@", str(REPO))
                      .replace("@PRIVATE_DIR@", str(private)))
    env = {k: v for k, v in os.environ.items() if k not in ("CREATEUR_ENV_FILE", "INSTANCE_PATH")}
    env.update({
        "GATEWAY_INTERFACE": "CGI/1.1", "REQUEST_METHOD": "GET", "REQUEST_URI": uri,
        "QUERY_STRING": uri.partition("?")[2], "SCRIPT_NAME": "/cgi-bin/createur.cgi", "PATH_INFO": "",
        "SERVER_NAME": "example.org", "SERVER_PORT": "443", "SERVER_PROTOCOL": "HTTP/1.1", "HTTPS": "on",
    })
    out = subprocess.run([sys.executable, str(script)], env=env, capture_output=True, timeout=60, cwd=tmp_path)
    return out.stdout.decode(), private


def _base_env(tmp_path):
    return [f"DATABASE_URL=sqlite:///{tmp_path / 'cgi.db'}", "BASE_URL=https://example.org", "DEMO_MODE=0",
            f"MEDIA_ROOT={tmp_path / 'media'}", f"PAGE_CACHE_ROOT={tmp_path / '_cache'}",
            f"PRIVATE_ROOT={tmp_path / 'private'}", "SECRET_KEY=test"]


def test_cgi_wrapper_serves_the_app_at_the_site_root(tmp_path):
    out, _ = _cgi(tmp_path, "/robots.txt", _base_env(tmp_path))
    assert out.startswith("Status: 200")
    assert "Disallow: /beheer/" in out and "cgi-bin" not in out

    # Links the app builds must not carry the script's path (SCRIPT_NAME is reset).
    out, _ = _cgi(tmp_path, "/_lang/en?next=/makers", _base_env(tmp_path))
    assert out.startswith("Status: 302") and "Location: /makers" in out


def test_cgi_wrapper_logs_a_startup_failure(tmp_path):
    out, private = _cgi(tmp_path, "/", [*_base_env(tmp_path), "DEMO_MODE=1"])
    assert out.startswith("Status: 500")
    assert "DEMO_MODE is on" in (private / "logs" / "cgi-error.log").read_text()


def _htaccess_cache_target(url_path: str) -> str | None:
    """Apply the .htaccess cache rules the way Apache does (pattern on the path without its /)."""
    rel = url_path[1:]
    for pattern, target in re.findall(r"^RewriteRule (\S+) (_cache/\S+) \[END\]$",
                                      (STRATO / "htaccess").read_text(), re.M):
        m = re.match(pattern, rel)
        if m:
            return re.sub(r"\$1", m.group(1) or "", target).replace("//", "/")
    return None


def test_htaccess_cache_rules_match_the_app_cache(app):
    from app.public import cache
    with app.app_context():
        for url in ["/", "/en/", "/makers", "/en/makers", "/jan-de-schaaf", "/en/over-ons"]:
            expected = cache.file_for(url).relative_to(cache.root())
            assert _htaccess_cache_target(url) == f"_cache/{expected}", url
    for url in ["/en", "/jan/", "/Jan", "/beheer/", "/static/x.css", "/jan/foo", "/en/a/b"]:
        assert _htaccess_cache_target(url) is None, url
