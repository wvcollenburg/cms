"""Invite-only sign-up (§7): a webmaster invites an e-mail address for a new maker page.

The page is created right away as a draft with the webmaster's chosen web address (D11), so the
address is reserved. Accepting the invite creates the account (or links an existing one by
e-mail), makes it a member of the page and logs the person in. The caller commits."""
import hashlib
import secrets
from datetime import timedelta
from types import SimpleNamespace

from flask import current_app, url_for
from flask_babel import gettext as _
from sqlalchemy import select

from app.audit import audit
from app.extensions import db
from app.mail import send_template
from app.models import Invite, MakerSpace, SpaceMember, User, UserRole, utcnow

INVITE_DAYS = 7


class InviteError(Exception):
    """`code`: used, expired, inactive_user."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _new_token(invite: Invite) -> str:
    token = secrets.token_urlsafe(32)
    invite.token_hash = _hash(token)
    invite.expires_at = utcnow() + timedelta(days=INVITE_DAYS)
    return token


def create(actor: User, *, email: str, display_name: str, ui_lang: str, space_name: str, slug: str,
           grants_webmaster: bool = False) -> tuple[Invite, str]:
    """Create the draft page and the invite. Slug and e-mail are validated by the caller."""
    space = MakerSpace(slug=slug, name=space_name, lang=ui_lang, status="draft")
    db.session.add(space)
    db.session.flush()
    invite = Invite(email=email, display_name=display_name, ui_lang=ui_lang, space_id=space.id,
                    grants_webmaster=grants_webmaster, invited_by=actor.id)
    token = _new_token(invite)
    db.session.add(invite)
    db.session.flush()
    audit("invite.created", "invite", invite.id,
          {"email": email, "space": slug, "grants_webmaster": grants_webmaster}, user=actor)
    return invite, token


def resend(actor: User, invite: Invite) -> str:
    """New link (the old one stops working) and a fresh 7 days."""
    token = _new_token(invite)
    audit("invite.resent", "invite", invite.id, {"email": invite.email}, user=actor)
    return token


def withdraw(actor: User, invite: Invite) -> None:
    """Delete the invite, and the draft page too if nobody has joined it yet."""
    space = invite.space
    audit("invite.withdrawn", "invite", invite.id, {"email": invite.email, "space": space.slug if space else None},
          user=actor)
    db.session.delete(invite)
    if space is not None and not space.members and space.status == "draft":
        db.session.delete(space)


def pending_for(space_ids) -> dict[int, Invite]:
    rows = db.session.scalars(select(Invite).where(Invite.space_id.in_(list(space_ids)), Invite.used_at.is_(None)))
    return {i.space_id: i for i in rows}


def find(token: str) -> Invite | None:
    return db.session.scalar(select(Invite).where(Invite.token_hash == _hash(token)))


def accept(token: str) -> tuple[User, Invite]:
    invite = find(token)
    if invite is None or invite.used_at is not None:
        raise InviteError("used")
    if invite.expires_at < utcnow():
        raise InviteError("expired")
    user = db.session.scalar(select(User).where(User.email == invite.email))
    if user is not None and not user.is_active:
        raise InviteError("inactive_user")
    if user is None:
        user = User(email=invite.email, display_name=invite.display_name, ui_lang=invite.ui_lang)
        db.session.add(user)
        db.session.flush()
    if invite.space_id and invite.space_id not in user.member_space_ids:
        db.session.add(SpaceMember(space_id=invite.space_id, user_id=user.id, role="owner"))
    if invite.grants_webmaster and not user.has_role("webmaster"):
        user.roles.append(UserRole(role="webmaster"))
    invite.used_at = utcnow()
    db.session.flush()
    db.session.refresh(user)
    audit("invite.accepted", "invite", invite.id, {"user_id": user.id}, user=user)
    return user, invite


def send(invite: Invite, token: str, inviter: User) -> None:
    recipient = SimpleNamespace(email=invite.email, display_name=invite.display_name, ui_lang=invite.ui_lang)
    base = current_app.config["BASE_URL"]
    send_template(
        recipient, "invite", lambda: _("Your own page at Broedplaats de Createur"),
        link=base + url_for("auth.invite", token=token), inviter=inviter.display_name, days=INVITE_DAYS,
        page_url=f"{base}/{invite.space.slug}" if invite.space else base, login_url=base + url_for("auth.login"),
    )
