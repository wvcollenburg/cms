"""Rendering shared by the public site and the admin preview (§6: preview uses the real template)."""
from flask import render_template
from sqlalchemy import select

from app.blocks import media_ids_in
from app.extensions import db
from app.models import Block, MakerSpace, Media, Page, SiteSetting


def setting(key: str, lang: str = "", default=None):
    row = db.session.scalar(select(SiteSetting).where(SiteSetting.key == key, SiteSetting.lang == lang))
    if row is None and lang:
        row = db.session.scalar(select(SiteSetting).where(SiteSetting.key == key, SiteSetting.lang == "nl"))
    return row.value if row else default


def nav_pages(lang: str) -> list[dict]:
    pages = db.session.scalars(
        select(Page).where(Page.status == "published", Page.show_in_nav.is_(True)).order_by(Page.nav_order)
    ).all()
    out = []
    for p in pages:
        t = p.translation(lang) or p.translation("nl")
        if t:
            out.append({"slug": p.slug, "title": t.title})
    return out


def load_blocks(owner_type: str, owner_id: int, lang: str | None, *, visible_only: bool = True):
    q = select(Block).where(Block.owner_type == owner_type, Block.owner_id == owner_id)
    q = q.where(Block.lang.is_(None) if lang is None else Block.lang == lang)
    if visible_only:
        q = q.where(Block.is_visible.is_(True))
    blocks = db.session.scalars(q.order_by(Block.position, Block.id)).all()
    ids = set()
    for b in blocks:
        ids |= media_ids_in(b.type, b.data)
    media = {}
    if ids:
        # Scoped to the same owner: a block can never show another owner's images.
        media = {m.id: m for m in db.session.scalars(
            select(Media).where(Media.id.in_(ids), Media.owner_type == owner_type, Media.owner_id == owner_id)
        )}
    return blocks, media


def published_spaces() -> list[MakerSpace]:
    return list(db.session.scalars(
        select(MakerSpace).where(MakerSpace.status == "published").order_by(MakerSpace.sort_order, MakerSpace.name)
    ))


def render_space(space: MakerSpace, *, preview: bool = False):
    blocks, media = load_blocks("space", space.id, None)
    others = [s for s in published_spaces() if s.id != space.id][:8]
    return render_template("public/space.html", space=space, blocks=blocks, media=media, preview=preview,
                           others=others)


def render_page(page: Page, lang: str, *, preview: bool = False):
    """Front page or static front page in `lang`; falls back to NL content with a notice."""
    t = page.translation(lang)
    content_lang = lang if t else "nl"
    t = t or page.translation("nl")
    blocks, media = load_blocks("page", page.id, content_lang)
    template = "public/home.html" if page.slug == "home" else "public/page.html"
    extra = {}
    if page.slug == "home":
        # The first photo on the front page is shown full-screen at the top instead of in the flow.
        hero = next((b for b in blocks if b.type == "image" and media.get(b.data.get("media_id"))), None)
        if hero:
            blocks = [b for b in blocks if b is not hero]
        extra = {"makers": published_spaces(), "hero": hero, "hero_media": media.get(hero.data["media_id"]) if hero else None}
    return render_template(
        template, page=page, t=t, blocks=blocks, media=media, content_lang=content_lang,
        only_dutch=content_lang != lang, preview=preview, **extra,
    )
