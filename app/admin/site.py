"""Webmaster: front pages and makers. Superadmin: offline makers (§3, §3a).

None of these views touch maker content (D3)."""
from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_required
from sqlalchemy import select

from app.admin import bp
from app.admin.editor import Target, _touch
from app.audit import audit
from app.auth import policy
from app.extensions import db
from app.lifecycle import REMOVE_ERRORS, LifecycleError, hidden_spaces, remove_maker, restore_space
from app.mail import send_template
from app import invites
from app.models import Invite, MakerSpace, Page, PageTranslation, SiteSetting, User, utcnow
from app.slugs import check_space_slug


def _require(check) -> None:
    if not check(current_user):
        abort(403)


# ------------------------------------------------------------------ front pages

@bp.get("/website")
@login_required
def site_pages():
    _require(policy.can_edit_site)
    pages = db.session.scalars(select(Page).order_by(Page.slug != "home", Page.nav_order, Page.slug)).all()
    return render_template("admin/site_pages.html", pages=pages)


@bp.post("/website/page/<int:page_id>")
@login_required
def page_meta(page_id):
    _require(policy.can_edit_site)
    page = db.get_or_404(Page, page_id)
    lang = request.form.get("lang", "nl")
    if lang not in current_app.config["LANGUAGES"]:
        abort(400)
    title = request.form.get("title", "").strip()
    t = page.translation(lang)
    if title:
        if t is None:
            t = PageTranslation(page=page, lang=lang, title=title)
            db.session.add(t)
        t.title = title[:200]
        t.meta_description = request.form.get("meta_description", "").strip()[:300]
    elif t is not None and lang != "nl":
        db.session.delete(t)  # no EN title → the EN URL shows NL content with a notice
    if "status" in request.form:
        page.status = "published" if request.form["status"] == "published" else "draft"
    if "show_in_nav" in request.form or "status" in request.form:
        page.show_in_nav = request.form.get("show_in_nav") == "1"
    audit("page.meta", "page", page.id, {"lang": lang})
    db.session.commit()
    _touch(Target("page", page, lang))
    flash(_("Saved."), "success")
    return redirect(url_for("admin.editor", kind="page", oid=page.id, lang=lang))


# ------------------------------------------------------------------ site settings

# (key, per language?) Everything a webmaster can change site-wide.
SETTINGS = (("tagline", True), ("marquee", True), ("address", False), ("contact_email", False))


def _get_setting_row(key: str, lang: str) -> SiteSetting | None:
    return db.session.scalar(select(SiteSetting).where(SiteSetting.key == key, SiteSetting.lang == lang))


def _set_setting(key: str, lang: str, value) -> None:
    row = _get_setting_row(key, lang)
    if value in (None, "", []):
        if row is not None:
            db.session.delete(row)
        return
    if row is None:
        db.session.add(SiteSetting(key=key, lang=lang, value=value))
    else:
        row.value = value


@bp.route("/website/instellingen", methods=["GET", "POST"])
@login_required
def site_settings():
    _require(policy.can_edit_site)
    langs = current_app.config["LANGUAGES"]
    if request.method == "POST":
        before = {}
        for key, per_lang in SETTINGS:
            for lang in (langs if per_lang else ("",)):
                field = f"{key}_{lang}" if lang else key
                raw = request.form.get(field, "").strip()
                if key == "marquee":
                    value = [w.strip()[:40] for w in raw.splitlines() if w.strip()][:12]
                else:
                    value = raw[:300]
                row = _get_setting_row(key, lang)
                before[field] = row.value if row else None
                _set_setting(key, lang, value)
        audit("site.settings", "site", "settings", {"before": before})
        db.session.commit()
        flash(_("Saved."), "success")
        return redirect(url_for("admin.site_settings"))
    values = {}
    for key, per_lang in SETTINGS:
        for lang in (langs if per_lang else ("",)):
            row = _get_setting_row(key, lang)
            v = row.value if row else ""
            values[f"{key}_{lang}" if lang else key] = "\n".join(v) if isinstance(v, list) else (v or "")
    return render_template("admin/site_settings.html", values=values)


# ------------------------------------------------------------------ makers

@bp.get("/makers")
@login_required
def makers():
    _require(policy.can_edit_site)
    spaces = db.session.scalars(select(MakerSpace).order_by(MakerSpace.status == "hidden", MakerSpace.name)).all()
    return render_template("admin/makers.html", spaces=spaces, pending=invites.pending_for(s.id for s in spaces),
                           now=utcnow())


SLUG_ERRORS = {
    "format": lambda: _("Use 3 to 40 lowercase letters, digits or hyphens, e.g. jan-de-vries."),
    "reserved": lambda: _("This web address is reserved for the website itself. Choose another."),
    "taken": lambda: _("This web address is already in use. Choose another."),
}


@bp.route("/makers/nieuw", methods=["GET", "POST"])
@login_required
def new_maker():
    _require(policy.can_invite)
    form = {"lang": "nl"}
    errors = {}
    if request.method == "POST":
        form = {k: request.form.get(k, "").strip() for k in ("space_name", "display_name", "email", "slug", "lang")}
        form["email"] = form["email"].lower()
        form["slug"] = form["slug"].lower()
        if not form["space_name"]:
            errors["space_name"] = _("Please fill this in.")
        if not form["display_name"]:
            errors["display_name"] = _("Please fill this in.")
        if "@" not in form["email"] or "." not in form["email"].split("@")[-1]:
            errors["email"] = _("This doesn't look like an e-mail address.")
        else:
            existing = db.session.scalar(select(User).where(User.email == form["email"]))
            if existing is not None and not existing.is_active:
                errors["email"] = _("This person was taken offline. A key holder can put them back.")
        slug_error = check_space_slug(form["slug"])
        if slug_error:
            errors["slug"] = SLUG_ERRORS[slug_error]()
        if form["lang"] not in current_app.config["LANGUAGES"]:
            form["lang"] = "nl"
        if not errors:
            grant = request.form.get("grants_webmaster") == "1" and policy.can_manage_roles(current_user)
            invite, token = invites.create(
                current_user, email=form["email"], display_name=form["display_name"][:120], ui_lang=form["lang"],
                space_name=form["space_name"][:120], slug=form["slug"], grants_webmaster=grant,
            )
            db.session.commit()
            invites.send(invite, token, current_user)
            flash(_("Invitation sent to %(email)s.", email=invite.email), "success")
            return redirect(url_for("admin.makers"))
    return render_template("admin/new_maker.html", form=form, errors=errors), (400 if errors else 200)


def _pending_invite_or_404(invite_id: int) -> Invite:
    invite = db.get_or_404(Invite, invite_id)
    if invite.used_at is not None:
        abort(404)
    return invite


@bp.post("/makers/uitnodiging/<int:invite_id>/opnieuw")
@login_required
def resend_invite(invite_id):
    _require(policy.can_invite)
    invite = _pending_invite_or_404(invite_id)
    token = invites.resend(current_user, invite)
    db.session.commit()
    invites.send(invite, token, current_user)
    flash(_("Invitation sent to %(email)s.", email=invite.email), "success")
    return redirect(url_for("admin.makers"))


@bp.post("/makers/uitnodiging/<int:invite_id>/intrekken")
@login_required
def withdraw_invite(invite_id):
    _require(policy.can_invite)
    invite = _pending_invite_or_404(invite_id)
    invites.withdraw(current_user, invite)
    db.session.commit()
    flash(_("Invitation withdrawn."), "success")
    return redirect(url_for("admin.makers"))


@bp.route("/makers/<int:space_id>/offline/<int:user_id>", methods=["GET", "POST"])
@login_required
def remove(space_id, user_id):
    _require(policy.can_remove_maker)
    space = db.get_or_404(MakerSpace, space_id)
    user = db.get_or_404(User, user_id)
    if user.id not in {m.user_id for m in space.members}:
        abort(404)
    affected = [m.space for m in user.memberships]
    errors = {}
    if request.method == "POST":
        confirm = request.form.get("confirm_slug", "").strip().lower()
        reason = request.form.get("reason", "").strip()
        if confirm != space.slug:
            errors["confirm_slug"] = _("Type the web address exactly as shown.")
        if not reason:
            errors["reason"] = _("Please give a reason.")
        if not errors:
            try:
                result = remove_maker(current_user, user, space, reason[:500])
            except LifecycleError as e:
                flash(str(REMOVE_ERRORS[e.code]), "error")
                return redirect(url_for("admin.makers"))
            db.session.commit()
            if result["hidden"]:
                send_template(user, "space_offline", lambda: _("Your page at Broedplaats de Createur is offline"),
                              spaces=result["hidden"], contact=current_app.config["MAIL_FROM"])
            flash(_("%(name)s is offline.", name=user.display_name), "success")
            return redirect(url_for("admin.makers"))
    return render_template("admin/remove.html", space=space, user=user, affected=affected, errors=errors,
                           purge_days=current_app.config["HIDE_DAYS"]), (400 if errors else 200)


# ------------------------------------------------------------------ superadmin: offline makers

@bp.get("/offline")
@login_required
def offline():
    _require(policy.can_manage_lifecycle)
    return render_template("admin/offline.html", spaces=hidden_spaces())


@bp.post("/offline/<int:space_id>/terugzetten")
@login_required
def restore(space_id):
    _require(policy.can_manage_lifecycle)
    space = db.get_or_404(MakerSpace, space_id)
    reason = request.form.get("reason", "").strip()
    if not reason:
        flash(_("Please give a reason."), "error")
        return redirect(url_for("admin.offline"))
    try:
        users = restore_space(current_user, space, reason[:500])
    except LifecycleError as e:
        flash(str(REMOVE_ERRORS[e.code]), "error")
        return redirect(url_for("admin.offline"))
    db.session.commit()
    for u in users:
        send_template(u, "space_restored", lambda: _("Your page at Broedplaats de Createur is back"), space=space)
    flash(_("%(name)s is back. The page is not visible yet: the maker decides when.", name=space.name), "success")
    return redirect(url_for("admin.offline"))
