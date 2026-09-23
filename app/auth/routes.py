"""Login (§7): magic link by default, optional password, demo shortcuts only with DEMO_MODE."""
import hashlib
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for
from flask_babel import gettext as _
from flask_babel import lazy_gettext as _l
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import select

from app.config import demo_host_allowed
from app.extensions import db
from app.mail import send_template
from app.models import LoginToken, User, utcnow
from app.ratelimit import hit

bp = Blueprint("auth", __name__, url_prefix="/auth")
ph = PasswordHasher()

DEMO_EMAIL_DOMAIN = "@demo.example.org"
WINDOW = timedelta(minutes=15)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _safe_next(target: str | None) -> str:
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return url_for("admin.dashboard")


def _client_ip() -> str:
    return request.remote_addr or "?"


def _do_login(user: User) -> None:
    next_url = session.get("next")
    session.clear()  # rotate the session on login (§7)
    login_user(user)
    user.last_login_at = utcnow()
    db.session.commit()
    if next_url:
        session["next"] = next_url


def _user_by_email(email: str) -> User | None:
    return db.session.scalar(select(User).where(User.email == email.strip().lower()))


@bp.get("/login")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("admin.dashboard"))
    if request.args.get("next"):
        session["next"] = _safe_next(request.args["next"])
    return render_template("auth/login.html")


@bp.post("/login")
def request_link():
    email = request.form.get("email", "").strip().lower()
    if not email or "@" not in email:
        flash(_("Please enter your e-mail address."), "error")
        return redirect(url_for("auth.login"))
    if not (hit(f"link:ip:{_client_ip()}", 20, WINDOW) and hit(f"link:email:{email}", 5, WINDOW)):
        flash(_("Too many attempts. Please wait 15 minutes and try again."), "error")
        return redirect(url_for("auth.login"))

    user = _user_by_email(email)
    if user and user.is_active:
        token = secrets.token_urlsafe(32)
        db.session.add(LoginToken(
            user_id=user.id, token_hash=_hash(token),
            expires_at=utcnow() + timedelta(minutes=current_app.config["MAGIC_LINK_MINUTES"]),
        ))
        db.session.commit()
        link = current_app.config["BASE_URL"] + url_for("auth.link", token=token)
        send_template(user, "login_link", lambda: _("Your login link for Broedplaats de Createur"),
                      link=link, minutes=current_app.config["MAGIC_LINK_MINUTES"])
    # Same answer whether or not the address is known.
    return render_template("auth/check_mail.html", email=email)


def _valid_token(token: str) -> LoginToken | None:
    row = db.session.scalar(select(LoginToken).where(LoginToken.token_hash == _hash(token)))
    if row is None or row.used_at is not None or row.expires_at < utcnow() or not row.user.is_active:
        return None
    return row


@bp.get("/link/<token>")
def link(token):
    # A page with a button, not an instant login: mail scanners that open links
    # would otherwise use up the single-use token.
    return render_template("auth/confirm_link.html", token=token, valid=_valid_token(token) is not None)


@bp.post("/link/<token>")
def use_link(token):
    row = _valid_token(token)
    if row is None:
        return render_template("auth/confirm_link.html", token=token, valid=False), 400
    row.used_at = utcnow()
    _do_login(row.user)
    return redirect(_safe_next(session.pop("next", None)))


@bp.post("/password")
def password_login():
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    if not (hit(f"pw:ip:{_client_ip()}", 30, WINDOW) and hit(f"pw:email:{email}", 10, WINDOW)):
        flash(_("Too many attempts. Please wait 15 minutes and try again."), "error")
        return redirect(url_for("auth.login"))
    user = _user_by_email(email)
    ok = False
    if user and user.is_active and user.password_hash:
        try:
            ok = ph.verify(user.password_hash, password)
        except (VerificationError, InvalidHashError):
            ok = False
    else:
        ph.hash(password or "x")  # similar timing for unknown addresses
    if not ok:
        flash(_("That e-mail address and password don't match."), "error")
        return redirect(url_for("auth.login"))
    if ph.check_needs_rehash(user.password_hash):
        user.password_hash = ph.hash(password)
    _do_login(user)
    return redirect(_safe_next(session.pop("next", None)))


@bp.post("/logout")
@login_required
def logout():
    logout_user()
    session.clear()
    flash(_("You are logged out."), "info")
    return redirect(url_for("public.home"))


# ------------------------------------------------------------------ demo (§10b)

def _demo_allowed() -> bool:
    cfg = current_app.config
    return cfg["DEMO_MODE"] and demo_host_allowed(request.host_url, cfg["DEMO_HOSTS"])


DEMO_LABELS = {
    "jan": _l("Maker A (Jan, furniture maker)"),
    "sanne": _l("Maker B (Sanne, shares a page with Bo)"),
    "noor": _l("Maker + webmaster (Noor)"),
    "sleutel": _l("Key holder (superadmin)"),
}


@bp.get("/demo")
def demo():
    if not _demo_allowed():
        abort(404)
    users = db.session.scalars(
        select(User).where(User.email.like(f"%{DEMO_EMAIL_DOMAIN}"), User.is_active.is_(True)).order_by(User.id)
    ).all()
    return render_template("auth/demo.html", users=users, labels=DEMO_LABELS)


@bp.post("/demo/<int:user_id>")
def demo_login(user_id):
    if not _demo_allowed():
        abort(404)
    user = db.session.get(User, user_id)
    if user is None or not user.email.endswith(DEMO_EMAIL_DOMAIN) or not user.is_active:
        abort(404)
    _do_login(user)
    return redirect(url_for("admin.dashboard"))
