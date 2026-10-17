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
    # Like Apache on STRATO: no HOME in the environment.
    env = {k: v for k, v in os.environ.items() if k not in ("CREATEUR_ENV_FILE", "INSTANCE_PATH", "HOME")}
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


def test_cgi_wrapper_expands_home_paths_without_HOME(tmp_path):
    # PRIVATE_DIR is <tmp>/private, so the wrapper takes <tmp> as home.
    photo = tmp_path / "media" / "site" / "x.webp"
    photo.parent.mkdir(parents=True)
    photo.write_bytes(b"RIFF")
    env = [line for line in _base_env(tmp_path) if not line.startswith("MEDIA_ROOT")] + ["MEDIA_ROOT=~/media"]
    out, _ = _cgi(tmp_path, "/media/site/x.webp", env)
    assert out.startswith("Status: 200"), out[:200]


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


def test_init_site_makes_the_front_pages_once(app, client):
    run = CliRunner().invoke
    assert client.get("/").status_code == 404  # a new site has no front page
    result = run(app.cli, ["init-site"])
    assert result.exit_code == 0, result.output
    assert client.get("/").status_code == 200 and "Bekijk alle makers" in client.get("/").get_data(as_text=True)
    assert client.get("/en/").status_code == 200
    assert client.get("/privacy").status_code == 200
    assert client.get("/over").status_code == 404  # drafts until the webmasters fill them
    assert client.get("/contact").status_code == 404

    from app.models import Page
    with app.app_context():
        db.session.get(Page, 1).status = "draft"  # a webmaster's change survives a second run
        db.session.commit()
    assert "already there" in run(app.cli, ["init-site"]).output
    with app.app_context():
        assert db.session.query(Page).count() == 4 and db.session.get(Page, 1).status == "draft"


def test_add_maker_before_the_e_mail_address_is_known(app, client, login):
    from app.models import MakerSpace
    run = CliRunner().invoke
    assert run(app.cli, ["add-maker", "Lobi Lampu", "Willemieke"]).exit_code == 0
    r = run(app.cli, ["add-maker", "Jaber & Wassem", "Jaber", "Wassem", "--slug", "jaber-en-wassem"])
    assert r.exit_code == 0, r.output
    assert "taken" in run(app.cli, ["add-maker", "Lobi Lampu", "Iemand"]).output  # same address twice
    assert "already exists" in run(app.cli, ["add-maker", "Ander", "Willemieke"]).output

    makers = client.get("/makers").get_data(as_text=True)
    assert "Lobi Lampu" in makers and "Jaber &amp; Wassem" in makers
    assert client.get("/lobi-lampu").status_code == 200
    out = run(app.cli, ["list-makers"]).output
    assert "willemieke@nog-geen-adres.invalid" in out and "wassem@nog-geen-adres.invalid" in out

    # Later: the real address, then the maker owns their page.
    r = run(app.cli, ["set-email", "Willemieke@nog-geen-adres.invalid", "Wil@Example.org"])
    assert r.exit_code == 0, r.output
    assert "already in use" in run(app.cli, ["set-email", "jaber@nog-geen-adres.invalid", "wil@example.org"]).output
    with app.app_context():
        wil = db.session.query(User).filter_by(email="wil@example.org").one()
        space = db.session.query(MakerSpace).filter_by(slug="lobi-lampu").one()
        space_id = space.id
    login(wil)
    assert client.get(f"/beheer/space/{space_id}/", follow_redirects=True).status_code == 200


def test_set_slug_moves_a_page_and_keeps_old_links_working(app, client):
    run = CliRunner().invoke
    run(app.cli, ["add-maker", "Sander", "Sander"])
    run(app.cli, ["add-maker", "Bert", "Bert"])
    assert client.get("/sander").status_code == 200  # also fills the page cache

    r = run(app.cli, ["set-slug", "/sander", "Sander-Houtwerk"])
    assert r.exit_code == 0, r.output
    assert client.get("/sander-houtwerk").status_code == 200
    r = client.get("/sander")  # the cached copy is gone too
    assert r.status_code == 301 and r.location.endswith("/sander-houtwerk")
    assert client.get("/sander/iets").location.endswith("/sander-houtwerk/iets")

    assert "taken" in run(app.cli, ["set-slug", "bert", "sander"]).output  # a redirect keeps it reserved
    assert "taken" in run(app.cli, ["set-slug", "bert", "sander-houtwerk"]).output
    assert "No maker page" in run(app.cli, ["set-slug", "niemand", "iets"]).output
    assert "reserved" in run(app.cli, ["set-slug", "bert", "makers"]).output

    # Back to the old address: allowed, and the redirect goes away.
    assert run(app.cli, ["set-slug", "sander-houtwerk", "sander"]).exit_code == 0
    assert client.get("/sander").status_code == 200
    assert client.get("/sander-houtwerk").status_code == 301

    # --no-redirect frees the old address (for pages nobody links to yet).
    assert run(app.cli, ["set-slug", "bert", "bert-meubels", "--no-redirect"]).exit_code == 0
    assert client.get("/bert").status_code == 404
    assert run(app.cli, ["add-maker", "Bert", "Bert Twee"]).exit_code == 0
