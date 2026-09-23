"""Maker removal lifecycle (§3a): published/draft → hidden → (purge, phase 2) → tombstone.

Views check permissions via policy.py first; these functions do the state change in one
transaction and write the audit entries. The caller commits."""
from datetime import timedelta

from flask import current_app
from flask_babel import lazy_gettext as _l
from sqlalchemy import delete, select

from app.audit import audit
from app.extensions import db
from app.media import storage
from app.models import LoginToken, MakerSpace, SpaceMember, User, new_session_token, utcnow


class LifecycleError(Exception):
    """`code`: self, superadmin, not_member, not_hidden."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def remove_maker(actor: User, user: User, space: MakerSpace, reason: str) -> dict:
    """Take `user` offline. Spaces where they are the last member get hidden; in shared
    spaces only their membership goes (D5). Returns {"hidden": [...], "left": [...]}."""
    if user.id == actor.id:
        raise LifecycleError("self")
    if user.is_superadmin:
        # Keeps the "at least one superadmin" rule simple: roles are revoked separately first.
        raise LifecycleError("superadmin")
    if space.id not in user.member_space_ids:
        raise LifecycleError("not_member")

    now = utcnow()
    purge_at = now + timedelta(days=current_app.config["HIDE_DAYS"])
    result = {"hidden": [], "left": []}

    user.is_active = False
    user.session_token = new_session_token()  # revokes every session
    db.session.execute(delete(LoginToken).where(LoginToken.user_id == user.id, LoginToken.used_at.is_(None)))

    for membership in list(user.memberships):
        s = membership.space
        others = [m for m in s.members if m.user_id != user.id]
        if others:
            db.session.delete(membership)
            result["left"].append(s)
            audit("space.member_removed", "space", s.id, {"user_id": user.id, "reason": reason}, user=actor)
        else:
            old_status = s.status
            s.status, s.hidden_at, s.purge_at = "hidden", now, purge_at
            s.hidden_by, s.hide_reason = actor.id, reason
            result["hidden"].append(s)
            audit("space.hidden", "space", s.id,
                  {"old_status": old_status, "purge_at": purge_at.isoformat(), "reason": reason}, user=actor)
    audit("user.removed", "user", user.id, {"reason": reason, "via_space": space.slug}, user=actor)
    db.session.flush()

    # Files last: if the DB transaction fails the files stay put.
    for s in result["hidden"]:
        storage.hide_space(s.id)
    return result


def restore_space(actor: User, space: MakerSpace, reason: str) -> list[User]:
    """Superadmin only (checked by the caller). Back to draft; members reactivated."""
    if space.status != "hidden":
        raise LifecycleError("not_hidden")
    old_purge = space.purge_at
    space.status, space.hidden_at, space.purge_at, space.hidden_by, space.hide_reason = "draft", None, None, None, None
    users = [m.user for m in space.members]
    for u in users:
        u.is_active = True
    audit("space.restored", "space", space.id,
          {"old_purge_at": old_purge.isoformat() if old_purge else None, "reason": reason,
           "reactivated": [u.id for u in users]}, user=actor)
    db.session.flush()
    storage.restore_space(space.id)
    return users


def hidden_spaces() -> list[MakerSpace]:
    return list(db.session.scalars(select(MakerSpace).where(MakerSpace.status == "hidden").order_by(MakerSpace.purge_at)))


REMOVE_ERRORS = {
    "self": _l("You can't take yourself offline."),
    "superadmin": _l("This person is a key holder. Remove that role first."),
    "not_member": _l("This person isn't a member of this maker page."),
    "not_hidden": _l("This maker page isn't offline."),
}
