"""One block editor for maker spaces and front pages (polymorphic owner, §4).

URLs: /beheer/<space|page>/<id>/...; front pages carry ?lang=nl|en (one block list per language).
Every view resolves the owner, runs the policy check, and scopes every block/media query to it.
"""
from dataclasses import dataclass

from flask import abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_required
from pydantic import ValidationError
from sqlalchemy import func, select

from app.admin import bp
from app.audit import audit
from app.auth import policy
from app.blocks import BLOCK_TYPES, media_ids_in, validate
from app.extensions import db
from app.media import UploadError, delete_media, get_owned, process_upload
from app.models import Block, MakerSpace, Page
from app.public.render import load_blocks, render_page, render_space

UPLOAD_ERRORS = {
    "too_big": lambda: _("This photo is too large (max. 15 MB)."),
    "bad_type": lambda: _("This file isn't a photo we can use. Use JPEG, PNG or WebP."),
    "quota": lambda: _("Your page is full (1 GB). Remove some photos first."),
}


@dataclass
class Target:
    kind: str  # 'space' | 'page'
    obj: MakerSpace | Page
    lang: str | None  # None for spaces

    @property
    def owner(self) -> tuple[str, int]:
        return self.kind, self.obj.id

    @property
    def title(self) -> str:
        if self.kind == "space":
            return self.obj.name
        t = self.obj.translation(self.lang) or self.obj.translation("nl")
        return t.title if t else self.obj.slug

    def url(self, endpoint: str, **kw) -> str:
        if self.lang:
            kw["lang"] = self.lang
        return url_for(endpoint, kind=self.kind, oid=self.obj.id, **kw)

    def blocks_query(self):
        q = select(Block).where(Block.owner_type == self.kind, Block.owner_id == self.obj.id)
        return q.where(Block.lang.is_(None) if self.lang is None else Block.lang == self.lang)

    def block_or_404(self, bid: int) -> Block:
        block = db.session.scalar(self.blocks_query().where(Block.id == bid))
        if block is None:
            abort(404)
        return block


def get_target(kind: str, oid: int) -> Target:
    if kind == "space":
        space = db.get_or_404(MakerSpace, oid)
        if not policy.can_edit_space(current_user, space):
            abort(403)
        return Target("space", space, None)
    if kind == "page":
        page = db.get_or_404(Page, oid)
        if not policy.can_edit_site(current_user):
            abort(403)
        lang = request.args.get("lang", "nl")
        if lang not in current_app.config["LANGUAGES"]:
            abort(404)
        return Target("page", page, lang)
    abort(404)


def _touch(target: Target) -> None:
    """Hook for the static page cache (Thu 24 Sep): invalidate what depends on this owner."""


def referenced_media(target: Target) -> set[int]:
    ids: set[int] = set()
    rows = db.session.scalars(select(Block).where(Block.owner_type == target.kind, Block.owner_id == target.obj.id))
    for b in rows:
        ids |= media_ids_in(b.type, b.data)
    if target.kind == "space":
        ids |= {i for i in (target.obj.avatar_media_id, target.obj.cover_media_id) if i}
    return ids


def cleanup_media(target: Target, candidates: set[int]) -> None:
    db.session.flush()
    still_used = referenced_media(target)
    for mid in candidates - still_used:
        m = get_owned(mid, *target.owner)
        if m:
            delete_media(m)


# ------------------------------------------------------------------ views

K = "/<any(space,page):kind>/<int:oid>"


@bp.get(K + "/")
@login_required
def editor(kind, oid):
    target = get_target(kind, oid)
    blocks, media = load_blocks(kind, oid, target.lang, visible_only=False)
    other_lang_count = 0
    if kind == "page":
        other_lang_count = db.session.scalar(
            select(func.count()).select_from(Block).where(
                Block.owner_type == "page", Block.owner_id == oid, Block.lang == ("nl" if target.lang == "en" else "en")
            )
        )
    return render_template("admin/editor.html", target=target, blocks=blocks, media=media,
                           other_lang_count=other_lang_count)


@bp.post(K + "/blocks")
@login_required
def add_block(kind, oid):
    target = get_target(kind, oid)
    btype = request.form.get("type")
    if btype not in BLOCK_TYPES:
        abort(400)
    last = db.session.scalar(target.blocks_query().with_only_columns(func.max(Block.position)))
    block = Block(owner_type=kind, owner_id=oid, lang=target.lang, type=btype,
                  position=(last or 0) + 1, data=validate(btype, {}), is_visible=False,
                  updated_by=current_user.id)
    db.session.add(block)
    db.session.flush()
    audit("block.added", "block", block.id, {"type": btype, "owner": f"{kind}:{oid}"})
    db.session.commit()
    return redirect(target.url("admin.edit_block", bid=block.id))


@bp.route(K + "/blocks/<int:bid>", methods=["GET", "POST"])
@login_required
def edit_block(kind, oid, bid):
    target = get_target(kind, oid)
    block = target.block_or_404(bid)
    btype = BLOCK_TYPES[block.type]
    error = None
    if request.method == "POST":
        before = media_ids_in(block.type, block.data)
        try:
            data = validate(block.type, btype.parse_form(request.form, dict(block.data)))
        except (ValidationError, ValueError) as e:
            error = _field_error(block.type, e)
        else:
            if block.type == "image" and data.get("media_id") and not get_owned(data["media_id"], *target.owner):
                abort(400)
            block.data = data
            block.updated_by = current_user.id
            if "make_visible" in request.form:
                block.is_visible = True
            audit("block.updated", "block", block.id, {"owner": f"{kind}:{oid}"})
            cleanup_media(target, before - media_ids_in(block.type, data))
            db.session.commit()
            _touch(target)
            flash(_("Saved."), "success")
            if request.form.get("then") == "stay":
                return redirect(target.url("admin.edit_block", bid=block.id))
            return redirect(target.url("admin.editor") + f"#block-{block.id}")
    media = load_blocks(kind, oid, target.lang, visible_only=False)[1]
    return render_template("admin/edit_block.html", target=target, block=block, btype=btype,
                           media=media, error=error), (400 if error else 200)


def _field_error(block_type: str, exc) -> str:
    if block_type == "video":
        return _("We don't recognise this video link. Copy the link from YouTube or Vimeo (the address bar or the Share button).")
    if block_type in ("cta", "image", "social"):
        return _("One of the web addresses isn't valid. Check for typos, e.g. https://www.example.nl")
    return _("Something in this form isn't right. Please check it.")


@bp.post(K + "/blocks/<int:bid>/toggle")
@login_required
def toggle_block(kind, oid, bid):
    target = get_target(kind, oid)
    block = target.block_or_404(bid)
    block.is_visible = not block.is_visible
    block.updated_by = current_user.id
    audit("block.visibility", "block", block.id, {"is_visible": block.is_visible})
    db.session.commit()
    _touch(target)
    return redirect(target.url("admin.editor") + f"#block-{block.id}")


@bp.post(K + "/blocks/<int:bid>/delete")
@login_required
def delete_block(kind, oid, bid):
    target = get_target(kind, oid)
    block = target.block_or_404(bid)
    used = media_ids_in(block.type, block.data)
    audit("block.deleted", "block", block.id, {"type": block.type, "owner": f"{kind}:{oid}"})
    db.session.delete(block)
    cleanup_media(target, used)
    db.session.commit()
    _touch(target)
    flash(_("Removed."), "success")
    return redirect(target.url("admin.editor"))


@bp.post(K + "/blocks/order")
@login_required
def order_blocks(kind, oid):
    target = get_target(kind, oid)
    ids = (request.get_json(silent=True) or {}).get("ids", [])
    blocks = {b.id: b for b in db.session.scalars(target.blocks_query())}
    if sorted(ids) != sorted(blocks):
        abort(400)
    for pos, bid in enumerate(ids, start=1):
        blocks[bid].position = pos
    db.session.commit()
    _touch(target)
    return jsonify(ok=True)


@bp.post(K + "/blocks/<int:bid>/upload")
@login_required
def upload_to_block(kind, oid, bid):
    """One photo per request (the browser resized it first). Gallery: appended; image: replaced."""
    target = get_target(kind, oid)
    block = target.block_or_404(bid)
    if block.type not in ("gallery", "image"):
        abort(400)
    file = request.files.get("file")
    if file is None:
        abort(400)
    try:
        m = process_upload(file, *target.owner, current_user, alt_text=request.form.get("alt", ""))
    except UploadError as e:
        db.session.rollback()
        return jsonify(ok=False, error=UPLOAD_ERRORS[e.code]()), 400
    data = dict(block.data)
    if block.type == "gallery":
        data["items"] = [*data.get("items", []), {"media_id": m.id, "caption": ""}]
        block.data = validate("gallery", data)
    else:
        old = data.get("media_id")
        data["media_id"] = m.id
        block.data = validate("image", data)
        if old:
            cleanup_media(target, {old})
    block.updated_by = current_user.id
    db.session.commit()
    _touch(target)
    return jsonify(ok=True, media_id=m.id)


@bp.post(K + "/media/<int:mid>/alt")
@login_required
def set_alt(kind, oid, mid):
    target = get_target(kind, oid)
    m = get_owned(mid, *target.owner) or abort(404)
    m.alt_text = request.form.get("alt", "")[:300]
    db.session.commit()
    return jsonify(ok=True)


@bp.post(K + "/copy-nl")
@login_required
def copy_nl(kind, oid):
    """Front pages: start the EN block list as a copy of NL, then translate (§4)."""
    target = get_target(kind, oid)
    if kind != "page" or target.lang != "en":
        abort(400)
    if db.session.scalar(target.blocks_query().with_only_columns(func.count())):
        flash(_("The English version already has content."), "error")
        return redirect(target.url("admin.editor"))
    nl_blocks = db.session.scalars(
        select(Block).where(Block.owner_type == "page", Block.owner_id == oid, Block.lang == "nl").order_by(Block.position)
    )
    for b in nl_blocks:
        db.session.add(Block(owner_type="page", owner_id=oid, lang="en", type=b.type, position=b.position,
                             data=dict(b.data), is_visible=b.is_visible, updated_by=current_user.id))
    audit("page.copied_nl_to_en", "page", oid)
    db.session.commit()
    flash(_("Copied the Dutch version. Now translate each part."), "success")
    return redirect(target.url("admin.editor"))


@bp.get(K + "/preview")
@login_required
def preview(kind, oid):
    target = get_target(kind, oid)
    if kind == "space":
        return render_space(target.obj, preview=True)
    from flask import g
    g.lang = target.lang
    return render_page(target.obj, target.lang, preview=True)
