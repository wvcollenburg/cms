"""Slug rules (D11, §2): one namespace shared by front pages, maker spaces and tombstones."""
import re

from sqlalchemy import select

from app.extensions import db
from app.models import MakerSpace, Page, SlugRedirect, SpaceTombstone

SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,38})[a-z0-9]$")

RESERVED = frozenset({
    "en", "nl", "admin", "beheer", "auth", "api", "static", "media", "makers", "nieuws", "news",
    "agenda", "over", "about", "contact", "privacy", "home", "login", "logout", "_cache", "cgi-bin",
    "sitemap.xml", "robots.txt", "favicon.ico", "galerij", "gallery", "zoeken", "search",
})

# Front pages may use these; maker spaces may not.
PAGE_ALLOWED_RESERVED = frozenset({"over", "about", "contact", "privacy", "home"})


def is_valid_format(slug: str) -> bool:
    return bool(SLUG_RE.match(slug or "")) and "--" not in slug


def slug_taken(slug: str, *, ignore_space_id: int | None = None, ignore_page_id: int | None = None) -> bool:
    space = db.session.scalar(select(MakerSpace).where(MakerSpace.slug == slug))
    if space and space.id != ignore_space_id:
        return True
    page = db.session.scalar(select(Page).where(Page.slug == slug))
    if page and page.id != ignore_page_id:
        return True
    if db.session.get(SpaceTombstone, slug):
        return True
    redirect = db.session.get(SlugRedirect, slug)
    return bool(redirect) and not (redirect.target_type == "space" and redirect.target_id == ignore_space_id)


def check_space_slug(slug: str, *, ignore_space_id: int | None = None) -> str | None:
    """Return an error key, or None when the slug is free and valid for a maker space."""
    if not is_valid_format(slug):
        return "format"
    if slug in RESERVED:
        return "reserved"
    if slug_taken(slug, ignore_space_id=ignore_space_id):
        return "taken"
    return None
