from flask_login import current_user

from app.extensions import db
from app.models import AuditLog


def audit(action: str, object_type: str, object_id, diff: dict | None = None, user=None):
    """Add an audit entry to the current transaction; the caller commits."""
    actor = user if user is not None else (current_user if current_user.is_authenticated else None)
    db.session.add(AuditLog(
        user_id=actor.id if actor else None,
        action=action,
        object_type=object_type,
        object_id=str(object_id),
        diff=diff,
    ))
