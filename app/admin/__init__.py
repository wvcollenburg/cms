from flask import Blueprint

bp = Blueprint("admin", __name__, url_prefix="/beheer")

from app.admin import dashboard, editor, site, space  # noqa: E402,F401  (registers routes)
