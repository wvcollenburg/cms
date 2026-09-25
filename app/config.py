import os
from urllib.parse import urlparse


def _bool(name, default="0"):
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure")
    BASE_URL = os.environ.get("BASE_URL", "http://localhost:5000").rstrip("/")

    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///dev.db")
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    MEDIA_ROOT = os.environ.get("MEDIA_ROOT", "instance/media")
    PRIVATE_ROOT = os.environ.get("PRIVATE_ROOT", "instance/private")
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 15 MB image + form overhead

    MAIL_SERVER = os.environ.get("MAIL_SERVER", "localhost")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "1025"))
    MAIL_USE_TLS = _bool("MAIL_USE_TLS")
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
    MAIL_FROM = os.environ.get("MAIL_FROM", "Broedplaats de Createur <noreply@example.org>")
    MAIL_SUPPRESS = False

    # Number of reverse proxies in front of the app whose X-Forwarded-* headers we trust (0 = none).
    PROXY_HOPS = int(os.environ.get("PROXY_HOPS", "0"))

    DEMO_MODE = _bool("DEMO_MODE")
    DEMO_HOSTS = [h.strip() for h in os.environ.get("DEMO_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
    DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", "createur-demo")

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = BASE_URL.startswith("https://")
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE

    BABEL_DEFAULT_LOCALE = "nl"
    # Relative to app/, or absolute. The dev container compiles into /tmp so the mounted code stays clean.
    BABEL_TRANSLATION_DIRECTORIES = os.environ.get("BABEL_TRANSLATION_DIRECTORIES", "translations")
    TEMPLATES_AUTO_RELOAD = _bool("TEMPLATES_AUTO_RELOAD")
    LANGUAGES = ("nl", "en")

    MAGIC_LINK_MINUTES = 15
    HIDE_DAYS = 60
    MAX_POSTPONE_DAYS = 365
    SPACE_QUOTA_BYTES = 1024 * 1024 * 1024


def demo_host_allowed(base_url: str, demo_hosts: list[str]) -> bool:
    host = urlparse(base_url).hostname or ""
    return any(host == h or host.endswith("." + h) for h in demo_hosts)
