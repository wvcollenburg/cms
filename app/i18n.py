"""Language selection (§2, D6-D8).

Front section: the URL decides (/ is NL, /en/ is EN). Maker pages, auth pages and the
"no longer active" 404: cookie, then Accept-Language, then NL. Admin: the user's ui_lang.
"""
from flask import current_app, g, request
from flask_login import current_user

LANG_COOKIE = "lang"


def visitor_lang() -> str:
    langs = current_app.config["LANGUAGES"]
    cookie = request.cookies.get(LANG_COOKIE)
    if cookie in langs:
        return cookie
    return request.accept_languages.best_match(langs) or "nl"


def select_locale() -> str:
    forced = getattr(g, "lang", None)
    if forced:
        return forced
    if request.path.startswith("/beheer") and current_user.is_authenticated:
        return current_user.ui_lang
    return visitor_lang()
