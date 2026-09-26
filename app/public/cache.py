"""Static page cache (D18, §8): published public pages are rendered once and kept as HTML files.

Layout: the URL path maps to `<PAGE_CACHE_ROOT>/<path>/index.html` (`/` → `index.html`,
`/en/` → `en/index.html`, `/jan` → `jan/index.html`), so Apache on STRATO can serve the file
straight from the URL. Under Gunicorn the public blueprint serves it before touching the database.

Invalidation: any committed change to content clears the whole cache. With fewer than 15 makers
a full rebuild costs seconds, and clearing everything can never leave a stale page behind.
A generation token guards against a render that started before the change storing old content.
"""
import os
import re
import secrets
import shutil
from itertools import chain
from pathlib import Path

from flask import current_app, has_app_context
from sqlalchemy import event
from sqlalchemy.orm import Session

GENERATION_FILE = ".generation"
# Tables whose changes never show on a public page. Anything else counts as content, so a new
# content table is covered without having to remember it here.
NOT_CONTENT = frozenset({
    "users", "user_roles", "login_tokens", "invites", "space_members", "audit_log", "rate_limits", "task_runs",
})
_PATH_RE = re.compile(r"^/(?:[a-z0-9-]+/)*(?:[a-z0-9-]+)?$")
_CODE_SUFFIXES = (".py", ".html", ".txt", ".po")
_SKIP_DIRS = frozenset({"__pycache__", "static"})


def root() -> Path:
    return Path(current_app.config["PAGE_CACHE_ROOT"])


def file_for(url_path: str) -> Path | None:
    """The cache file for a URL path, or None if the path can't be cached."""
    if not _PATH_RE.match(url_path) or "//" in url_path:
        return None
    return root().joinpath(*[p for p in url_path.split("/") if p], "index.html")


def generation() -> str:
    try:
        return (root() / GENERATION_FILE).read_text()
    except FileNotFoundError:
        return ""


def lookup(url_path: str) -> Path | None:
    path = file_for(url_path)
    return path if path is not None and path.is_file() else None


def store(url_path: str, html: bytes, token: str) -> bool:
    """Write the page, unless the cache was cleared since `token` was read. Returns True if kept."""
    path = file_for(url_path)
    if path is None or token != generation():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}")
    tmp.write_bytes(html)
    os.replace(tmp, path)
    # A clear() that ran while we were writing bumped the generation first: drop our copy.
    if generation() != token:
        path.unlink(missing_ok=True)
        return False
    return True


def clear() -> None:
    """Bump the generation first (so in-flight renders won't store), then delete every page."""
    base = root()
    base.mkdir(parents=True, exist_ok=True)
    tmp = base / f".{GENERATION_FILE}.{secrets.token_hex(4)}"
    tmp.write_text(secrets.token_hex(8))
    os.replace(tmp, base / GENERATION_FILE)
    for child in base.iterdir():
        if child.name == GENERATION_FILE:
            continue
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)


def clear_if_code_changed() -> None:
    """Development only (TEMPLATES_AUTO_RELOAD): code or templates edited since the last clear → clear.

    With mounted code and auto-reload (compose.dev.yaml) a `git pull` changes pages without a
    restart, so the entrypoint's clear doesn't run."""
    gen_file = root() / GENERATION_FILE
    built = gen_file.stat().st_mtime if gen_file.exists() else 0
    for dirpath, dirs, files in os.walk(current_app.root_path):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for f in files:
            if f.endswith(_CODE_SUFFIXES) and os.stat(os.path.join(dirpath, f)).st_mtime > built:
                clear()
                return


def public_urls() -> list[str]:
    """Every URL the cache can hold: used to warm it after a clear."""
    from sqlalchemy import select

    from app.extensions import db
    from app.models import MakerSpace, Page

    urls = ["/", "/en/", "/makers", "/en/makers"]
    for page in db.session.scalars(select(Page).where(Page.status == "published", Page.slug != "home")):
        urls += [f"/{page.slug}", f"/en/{page.slug}"]
    for space in db.session.scalars(select(MakerSpace).where(MakerSpace.status == "published")):
        urls.append(f"/{space.slug}")
    return urls


# --- Invalidation on commit -------------------------------------------------------------------

def _is_content(table: str | None) -> bool:
    return table is not None and table not in NOT_CONTENT


@event.listens_for(Session, "after_flush")
def _note_flush(session, flush_context):
    if session.info.get("page_cache_dirty"):
        return
    if any(_is_content(getattr(o, "__tablename__", None)) for o in chain(session.new, session.dirty, session.deleted)):
        session.info["page_cache_dirty"] = True


@event.listens_for(Session, "do_orm_execute")
def _note_bulk(state):
    # Bulk update()/delete()/insert() statements bypass the flush.
    if state.is_update or state.is_delete or state.is_insert:
        if any(_is_content(m.local_table.name) for m in state.all_mappers):
            state.session.info["page_cache_dirty"] = True


@event.listens_for(Session, "after_commit")
def _clear_on_commit(session):
    if session.info.pop("page_cache_dirty", False) and has_app_context() and current_app.config["PAGE_CACHE"]:
        clear()


@event.listens_for(Session, "after_rollback")
def _forget_on_rollback(session):
    session.info.pop("page_cache_dirty", None)
