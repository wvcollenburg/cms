from flask import current_app, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_required

from app.admin import bp
from app.auth import policy
from app.auth.routes import ph
from app.extensions import db
from app.lifecycle import hidden_spaces
from app.models import new_session_token


@bp.get("/")
@login_required
def dashboard():
    spaces = [m.space for m in current_user.memberships]
    return render_template(
        "admin/dashboard.html",
        spaces=spaces,
        hidden=hidden_spaces() if policy.can_manage_lifecycle(current_user) else [],
    )


@bp.route("/profiel", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        name = request.form.get("display_name", "").strip()
        lang = request.form.get("ui_lang")
        if name:
            current_user.display_name = name[:120]
        if lang in current_app.config["LANGUAGES"]:
            current_user.ui_lang = lang
        pw = request.form.get("password", "")
        if request.form.get("remove_password"):
            current_user.password_hash = None
        elif pw:
            if len(pw) < 10:
                flash(_("Choose a password of at least 10 characters."), "error")
                return redirect(url_for("admin.profile"))
            current_user.password_hash = ph.hash(pw)
        db.session.commit()
        flash(_("Saved."), "success")
        return redirect(url_for("admin.profile"))
    return render_template("admin/profile.html")


@bp.post("/profiel/overal-uitloggen")
@login_required
def logout_everywhere():
    current_user.session_token = new_session_token()
    db.session.commit()
    flash(_("You are logged out on all devices."), "info")
    return redirect(url_for("auth.login"))
