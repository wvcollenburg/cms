"""Public site (§2, §8). Registered last: /<slug> is the catch-all."""
from flask import (
    Blueprint, abort, current_app, g, make_response, redirect, render_template, request, send_file, url_for,
)
from flask_babel import get_locale
from sqlalchemy import select

from app.extensions import db
from app.i18n import LANG_COOKIE, visitor_lang
from app.media import storage
from app.models import MakerSpace, Page, SlugRedirect, SpaceTombstone
from app.public.render import nav_pages, published_spaces, render_page, render_space, setting

bp = Blueprint("public", __name__)


def front_url(what: str = "home", lang: str | None = None) -> str:
    """URL of a front-section page in `lang` (NL at the root, EN under /en/)."""
    lang = lang or str(get_locale())
    prefix = "/en" if lang == "en" else ""
    if what == "home":
        return prefix + "/"
    return f"{prefix}/{what}"


@bp.app_context_processor
def site_context():
    return {"nav_pages": nav_pages, "setting": setting, "front_url": front_url}


def _front_page(slug: str, lang: str):
    g.lang = lang
    page = db.session.scalar(select(Page).where(Page.slug == slug, Page.status == "published"))
    if page is None:
        abort(404)
    return render_page(page, lang)


@bp.get("/")
def home():
    return _front_page("home", "nl")


@bp.get("/en/")
def home_en():
    return _front_page("home", "en")


@bp.get("/home")
def home_alias():
    return redirect(url_for("public.home"), 301)


@bp.get("/makers")
def makers():
    g.lang = "nl"
    return render_template("public/makers.html", spaces=published_spaces())


@bp.get("/en/makers")
def makers_en():
    g.lang = "en"
    return render_template("public/makers.html", spaces=published_spaces())


@bp.get("/en/<slug>")
def page_en(slug):
    return _front_page(slug, "en")


@bp.get("/_lang/<code>")
def set_lang(code):
    """Language toggle. The cookie is functional, so no banner is needed (§8)."""
    if code not in current_app.config["LANGUAGES"]:
        abort(404)
    target = request.args.get("next", "/")
    if not target.startswith("/") or target.startswith("//"):
        target = "/"
    resp = redirect(target)
    resp.set_cookie(LANG_COOKIE, code, max_age=365 * 24 * 3600, samesite="Lax",
                    secure=request.is_secure, httponly=True)
    return resp


@bp.get("/media/<path:key>")
def media(key):
    # On STRATO Apache serves these directly; hidden spaces' folders are moved away (§10a).
    folder = key.split("/", 1)[0]
    if folder.isdigit():
        space = db.session.get(MakerSpace, int(folder))
        if space is None or space.status == "hidden":
            abort(404)
    elif folder != "site":
        abort(404)
    path = storage.resolve(key)
    if path is None:
        abort(404)
    return send_file(path, max_age=365 * 24 * 3600)


@bp.get("/robots.txt")
def robots():
    if current_app.config["DEMO_MODE"]:
        body = "User-agent: *\nDisallow: /\n"
    else:
        body = f"User-agent: *\nDisallow: /beheer/\nDisallow: /auth/\nSitemap: {current_app.config['BASE_URL']}/sitemap.xml\n"
    resp = make_response(body)
    resp.mimetype = "text/plain"
    return resp


def _inactive(display_name: str | None):
    """The "no longer active" 404 (D8), in the visitor's language, never indexed."""
    g.lang = visitor_lang()
    resp = make_response(render_template("public/inactive.html", display_name=display_name), 404)
    resp.headers["X-Robots-Tag"] = "noindex"
    return resp


@bp.get("/<slug>")
def resolve(slug):
    """Resolution order (§2): live space, hidden space, tombstone, front page, redirect, 404."""
    space = db.session.scalar(select(MakerSpace).where(MakerSpace.slug == slug))
    if space is not None and space.status == "published":
        return render_space(space)
    if space is not None and space.status == "hidden":
        return _inactive(space.name)
    tomb = db.session.get(SpaceTombstone, slug)
    if tomb is not None:
        return _inactive(tomb.display_name)
    if slug != "home":
        page = db.session.scalar(select(Page).where(Page.slug == slug, Page.status == "published"))
        if page is not None:
            g.lang = "nl"
            return render_page(page, "nl")
    redirect_row = db.session.get(SlugRedirect, slug)
    if redirect_row is not None:
        target = _redirect_target(redirect_row)
        if target:
            return redirect(target, 301)
    abort(404)


@bp.get("/<slug>/<path:rest>")
def resolve_sub(slug, rest):
    """Sub-URLs of a maker space (articles, galleries: phase 2). Hidden → inactive page."""
    space = db.session.scalar(select(MakerSpace).where(MakerSpace.slug == slug))
    if space is not None and space.status == "hidden":
        return _inactive(space.name)
    tomb = db.session.get(SpaceTombstone, slug)
    if tomb is not None:
        return _inactive(tomb.display_name)
    redirect_row = db.session.get(SlugRedirect, slug)
    if redirect_row is not None:
        target = _redirect_target(redirect_row)
        if target:
            return redirect(f"{target}/{rest}", 301)
    abort(404)


def _redirect_target(row: SlugRedirect) -> str | None:
    if row.target_type == "space":
        space = db.session.get(MakerSpace, row.target_id)
        return url_for("public.resolve", slug=space.slug) if space else None
    page = db.session.get(Page, row.target_id)
    return url_for("public.resolve", slug=page.slug) if page else None
