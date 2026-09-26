"""Static page cache (D18): what gets stored, what is served, and that every change clears it."""
import threading

from click.testing import CliRunner

from app.extensions import db
from app.lifecycle import remove_maker
from app.models import AuditLog, Block, SiteSetting, User
from app.public import cache


def _cached(url):
    path = cache.file_for(url)
    return path.read_text() if path is not None and path.is_file() else None


def test_pages_are_stored_then_served_from_file(make_user, make_space, make_page, client):
    make_page("home")
    make_space("jan-hout", [make_user("jan")])
    for url in ("/", "/en/", "/makers", "/en/makers", "/jan-hout"):
        first = client.get(url)
        assert first.status_code == 200 and first.headers["X-Page-Cache"] == "MISS", url
        assert _cached(url) == first.get_data(as_text=True)
        second = client.get(url)
        assert second.headers["X-Page-Cache"] == "HIT" and second.data == first.data
        assert second.headers["Cache-Control"] == "no-cache"


def test_served_from_file_without_touching_the_database(make_user, make_space, client):
    make_space("jan-hout", [make_user("jan")])
    client.get("/jan-hout")
    # Change the DB behind the cache's back (no commit hook): the file must still be served.
    db.session.execute(db.text("UPDATE blocks SET data = '{\"html\": \"<p>sneaky</p>\"}'"))
    db.session.connection().commit()
    assert b"Hello from jan-hout" in client.get("/jan-hout").data


def test_public_pages_carry_nothing_per_visitor(make_user, make_space, make_page, client):
    make_page("home")
    make_space("jan-hout", [make_user("jan")])
    for url in ("/", "/jan-hout", "/makers"):
        resp = client.get(url)
        assert "csrf" not in resp.get_data(as_text=True).lower(), url
        assert "Set-Cookie" not in resp.headers, url


def test_not_stored(make_user, make_space, make_page, client):
    make_page("home")
    make_space("draft-space", [make_user("d")], status="draft")
    make_space("gone", [make_user("g")], status="hidden")
    assert client.get("/draft-space").status_code == 404
    assert client.get("/gone").status_code == 404
    assert client.get("/nothing").status_code == 404
    assert client.get("/?utm=x").headers.get("X-Page-Cache") is None
    assert client.get("/_lang/en?next=/").status_code == 302
    assert client.get("/robots.txt").headers.get("X-Page-Cache") is None
    stored = [p for p in cache.root().rglob("index.html")] if cache.root().exists() else []
    assert stored == []


def test_every_content_change_clears(make_user, make_space, make_page, client):
    make_page("home")
    s = make_space("jan-hout", [make_user("jan")])
    client.get("/jan-hout")
    client.get("/")
    assert _cached("/jan-hout") and _cached("/")

    db.session.add(Block(owner_type="space", owner_id=s.id, type="text", position=2,
                         data={"html": "<p>New work</p>"}, is_visible=True))
    db.session.commit()
    assert _cached("/jan-hout") is None and _cached("/") is None
    assert b"New work" in client.get("/jan-hout").data

    client.get("/")
    db.session.add(SiteSetting(key="address", lang="", value="Werkplaatsstraat 1"))
    db.session.commit()
    assert _cached("/") is None
    assert b"Werkplaatsstraat 1" in client.get("/").data


def test_non_content_changes_keep_the_cache(make_user, make_space, client):
    u = make_user("jan")
    make_space("jan-hout", [u])
    client.get("/jan-hout")
    u.last_login_at = None
    db.session.add(AuditLog(user_id=u.id, action="user.login", object_type="user", object_id=str(u.id)))
    db.session.commit()
    assert _cached("/jan-hout") is not None


def test_rollback_does_not_clear(make_user, make_space, client):
    s = make_space("jan-hout", [make_user("jan")])
    client.get("/jan-hout")
    s.name = "Changed"
    db.session.flush()
    db.session.rollback()
    assert _cached("/jan-hout") is not None


def test_hiding_a_maker_removes_the_page_at_once(make_user, make_space, client):
    jan = make_user("jan")
    web = make_user("web", roles=("webmaster",))
    space = make_space("jan-hout", [jan])
    assert client.get("/jan-hout").status_code == 200
    remove_maker(web, jan, space, "test")
    db.session.commit()
    assert _cached("/jan-hout") is None
    assert client.get("/jan-hout").status_code == 404


def test_render_during_a_change_is_not_stored(app, make_user, make_space):
    make_space("jan-hout", [make_user("jan")])
    token = cache.generation()
    cache.clear()  # a content change lands while an older render is still running
    assert cache.store("/jan-hout", b"<p>old</p>", token) is False
    assert _cached("/jan-hout") is None


def test_clear_while_writing_drops_the_write(app, monkeypatch):
    token = cache.generation()
    real_replace = cache.os.replace
    cleared = threading.Event()

    def replace_then_clear(src, dst):
        real_replace(src, dst)
        if str(dst).endswith("index.html") and not cleared.is_set():
            cleared.set()
            cache.clear()

    monkeypatch.setattr(cache.os, "replace", replace_then_clear)
    assert cache.store("/jan-hout", b"<p>old</p>", token) is False
    assert _cached("/jan-hout") is None


def test_file_mapping_rejects_odd_paths(app):
    root = cache.root()
    assert cache.file_for("/") == root / "index.html"
    assert cache.file_for("/en/") == root / "en" / "index.html"
    assert cache.file_for("/jan-hout") == root / "jan-hout" / "index.html"
    for bad in ("/../etc", "/Jan", "/a//b", "/jan.html", "/%2e%2e", "jan"):
        assert cache.file_for(bad) is None, bad


def test_cli_clear_and_warm(app, make_user, make_space, make_page):
    make_page("home")
    make_page("over", en=False)
    make_space("jan-hout", [make_user("jan")])
    make_space("draft-space", [make_user("d")], status="draft")
    runner = CliRunner()
    result = runner.invoke(app.cli, ["page-cache", "warm"])
    assert result.exit_code == 0, result.output
    assert "7 pages" in result.output  # / /en/ /makers /en/makers /over /en/over /jan-hout
    assert _cached("/draft-space") is None
    runner.invoke(app.cli, ["page-cache", "clear"])
    assert _cached("/") is None


def test_cache_can_be_switched_off(app, make_page, client):
    app.config["PAGE_CACHE"] = False
    make_page("home")
    assert client.get("/").headers.get("X-Page-Cache") is None
    assert _cached("/") is None


def test_dev_mode_clears_after_a_code_change(app, monkeypatch, tmp_path):
    import os
    code = tmp_path / "code"
    (code / "__pycache__").mkdir(parents=True)
    (code / "render.py").write_text("x = 1")
    (code / "__pycache__" / "render.pyc").write_text("")
    monkeypatch.setattr(app, "root_path", str(code))
    cache.clear()
    cache.store("/jan", b"<p>page</p>", cache.generation())
    built = (cache.root() / cache.GENERATION_FILE).stat().st_mtime
    os.utime(code / "render.py", (built - 10, built - 10))
    os.utime(code / "__pycache__" / "render.pyc", (built + 10, built + 10))  # ignored
    cache.clear_if_code_changed()
    assert _cached("/jan") is not None
    os.utime(code / "render.py", (built + 10, built + 10))  # a git pull
    cache.clear_if_code_changed()
    assert _cached("/jan") is None


def test_user_changes_are_not_content(app):
    assert User.__tablename__ in cache.NOT_CONTENT
