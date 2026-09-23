"""A maker's own space: settings, profile photo, cover, visible/not visible (§6)."""
import re

from flask import abort, flash, jsonify, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_required

from app.admin import bp
from app.admin.editor import UPLOAD_ERRORS, Target, _touch, cleanup_media
from app.audit import audit
from app.auth import policy
from app.blocks import sanitize_html
from app.extensions import db
from app.media import UploadError, process_upload
from app.models import MakerSpace

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _space_or_403(space_id: int) -> MakerSpace:
    space = db.get_or_404(MakerSpace, space_id)
    if not policy.can_edit_space(current_user, space):
        abort(403)
    return space


@bp.route("/space/<int:space_id>/instellingen", methods=["GET", "POST"])
@login_required
def space_settings(space_id):
    space = _space_or_403(space_id)
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash(_("Your page needs a name."), "error")
            return redirect(url_for("admin.space_settings", space_id=space.id))
        space.name = name[:120]
        space.tagline = request.form.get("tagline", "").strip()[:200]
        space.discipline = request.form.get("discipline", "").strip()[:80]
        space.bio_html = sanitize_html(request.form.get("bio_html", ""))
        if request.form.get("lang") in ("nl", "en"):
            space.lang = request.form["lang"]
        color = request.form.get("accent_color", "")
        if HEX.match(color):
            space.accent_color = color.lower()
        audit("space.settings", "space", space.id)
        db.session.commit()
        _touch(Target("space", space, None))
        flash(_("Saved."), "success")
        return redirect(url_for("admin.space_settings", space_id=space.id))
    return render_template("admin/space_settings.html", space=space)


@bp.post("/space/<int:space_id>/foto/<any(avatar,cover):which>")
@login_required
def space_photo(space_id, which):
    space = _space_or_403(space_id)
    target = Target("space", space, None)
    attr = f"{which}_media_id"
    old = getattr(space, attr)
    if request.form.get("remove"):
        setattr(space, attr, None)
    else:
        file = request.files.get("file")
        if file is None:
            abort(400)
        try:
            m = process_upload(file, "space", space.id, current_user, alt_text=space.name)
        except UploadError as e:
            db.session.rollback()
            return jsonify(ok=False, error=UPLOAD_ERRORS[e.code]()), 400
        setattr(space, attr, m.id)
    if old:
        cleanup_media(target, {old})
    audit(f"space.{which}", "space", space.id)
    db.session.commit()
    _touch(target)
    if request.form.get("remove"):
        return redirect(url_for("admin.space_settings", space_id=space.id))
    return jsonify(ok=True)


@bp.post("/space/<int:space_id>/zichtbaar")
@login_required
def space_visibility(space_id):
    space = _space_or_403(space_id)
    new = "published" if request.form.get("visible") == "1" else "draft"
    if space.status != new:
        audit("space.status", "space", space.id, {"old": space.status, "new": new})
        space.status = new
        db.session.commit()
        _touch(Target("space", space, None))
    flash(_("Your page is now visible to everyone.") if new == "published"
          else _("Your page is hidden from visitors for now."), "success")
    return redirect(request.form.get("back") or url_for("admin.editor", kind="space", oid=space.id))
