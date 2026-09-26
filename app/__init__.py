import os

from dotenv import load_dotenv
from flask import Flask, render_template, request


def create_app(overrides: dict | None = None) -> Flask:
    load_dotenv(os.environ.get("CREATEUR_ENV_FILE") or None)
    from app.config import Config, demo_host_allowed

    app = Flask(__name__, instance_path=os.path.abspath(os.environ.get("INSTANCE_PATH", "instance")))
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)
    os.makedirs(app.instance_path, exist_ok=True)

    # §10b: demo shortcuts must never reach production.
    if app.config["DEMO_MODE"] and not demo_host_allowed(app.config["BASE_URL"], app.config["DEMO_HOSTS"]):
        raise RuntimeError("DEMO_MODE is on but BASE_URL is not a demo host; refusing to start.")

    if app.config["PROXY_HOPS"]:
        from werkzeug.middleware.proxy_fix import ProxyFix
        n = app.config["PROXY_HOPS"]
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=n, x_proto=n, x_host=n)

    from app.extensions import babel, csrf, db, login_manager, migrate
    from app.i18n import select_locale

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    babel.init_app(app, locale_selector=select_locale)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.session_protection = "strong"

    from flask_babel import lazy_gettext as _l
    login_manager.login_message = _l("Please log in first.")

    @login_manager.user_loader
    def load_user(user_id: str):
        from app.models import User
        uid, _, token = user_id.partition(".")
        if not uid.isdigit():
            return None
        user = db.session.get(User, int(uid))
        if user is None or not user.is_active or user.session_token != token:
            return None
        return user

    _register_template_helpers(app)
    _register_security_headers(app)

    from app.admin import bp as admin_bp
    from app.auth.routes import bp as auth_bp
    from app.public.routes import bp as public_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(public_bp)  # last: it owns the /<slug> catch-all

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    from app.cli import register_cli
    register_cli(app)
    return app


def _register_template_helpers(app: Flask) -> None:
    from flask_babel import get_locale

    from app import media
    from app.auth import policy
    from app.blocks import BLOCK_TYPES, SOCIAL_PLATFORMS, trix_html

    @app.context_processor
    def inject():
        return {
            "policy": policy,
            "BLOCK_TYPES": BLOCK_TYPES,
            "SOCIAL_PLATFORMS": SOCIAL_PLATFORMS,
            "demo_mode": app.config["DEMO_MODE"],
            "ui_lang": str(get_locale()),
        }

    app.jinja_env.globals.update(
        media_url=media.media_url, srcset=media.srcset, img_src=media.src, img_fallback=media.fallback,
        focus_style=media.focus_style,
    )
    app.jinja_env.filters["trix"] = trix_html


def _register_security_headers(app: Flask) -> None:
    @app.after_request
    def headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        if request.path.startswith(("/beheer", "/auth")):
            resp.headers["Cache-Control"] = "no-store"
            resp.headers["X-Robots-Tag"] = "noindex"
        if app.config["DEMO_MODE"]:
            resp.headers["X-Robots-Tag"] = "noindex, nofollow"
        return resp
