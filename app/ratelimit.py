"""DB-backed fixed-window rate limiter: under CGI there's no shared memory and no Redis (§7)."""
from datetime import timedelta

from app.extensions import db
from app.models import RateLimit, utcnow


def hit(key: str, limit: int, window: timedelta) -> bool:
    """Count one attempt for `key`. Returns False when the limit is exceeded."""
    key = key[:190]
    now = utcnow()
    row = db.session.get(RateLimit, key, with_for_update=True)
    if row is None:
        row = RateLimit(key=key, window_start=now, count=0)
        db.session.add(row)
    elif row.window_start < now - window:
        row.window_start, row.count = now, 0
    row.count += 1
    db.session.commit()
    return row.count <= limit
