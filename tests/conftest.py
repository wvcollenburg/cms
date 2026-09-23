import io
import os

import pytest
from flask.testing import FlaskClient

os.environ["CREATEUR_ENV_FILE"] = os.devnull  # never pick up the developer's .env

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.mail import outbox  # noqa: E402
from app.models import Block, MakerSpace, Page, PageTranslation, SpaceMember, User, UserRole  # noqa: E402


class FreshContextClient(FlaskClient):
    """Run each request in its own app context, like production does, so `g` (current user,
    locale) and the DB session aren't shared with the test body or earlier requests."""

    def open(self, *args, **kwargs):
        with self.application.app_context():
            resp = super().open(*args, **kwargs)
        db.session.expire_all()
        return resp


@pytest.fixture
def app(tmp_path):
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.db'}",
        "WTF_CSRF_ENABLED": False,
        "MAIL_SUPPRESS": True,
        "MEDIA_ROOT": str(tmp_path / "media"),
        "PRIVATE_ROOT": str(tmp_path / "private"),
        "DEMO_MODE": False,
        "BASE_URL": "http://localhost",
        "SERVER_NAME": "localhost",
    })
    app.test_client_class = FreshContextClient
    with app.app_context():
        db.create_all()
        outbox.clear()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def make_user(app):
    def _make(key, roles=(), lang="nl", active=True):
        u = User(email=f"{key}@example.org", display_name=key.title(), ui_lang=lang, is_active=active)
        u.roles = [UserRole(role=r) for r in roles]
        db.session.add(u)
        db.session.commit()
        return u
    return _make


@pytest.fixture
def make_space(app):
    def _make(slug, members, status="published"):
        s = MakerSpace(slug=slug, name=slug.replace("-", " ").title(), status=status)
        s.members = [SpaceMember(user=u) for u in members]
        db.session.add(s)
        db.session.flush()
        db.session.add(Block(owner_type="space", owner_id=s.id, type="text", position=1,
                             data={"html": f"<p>Hello from {slug}</p>"}, is_visible=True))
        db.session.commit()
        return s
    return _make


@pytest.fixture
def make_page(app):
    def _make(slug="home", en=True):
        p = Page(slug=slug, status="published")
        p.translations = [PageTranslation(lang="nl", title=f"{slug} NL")]
        if en:
            p.translations.append(PageTranslation(lang="en", title=f"{slug} EN"))
        db.session.add(p)
        db.session.commit()
        return p
    return _make


@pytest.fixture
def login(app, client):
    """Put the user in the session like login_user does (id includes the session token)."""
    from flask_login.utils import _create_identifier

    def _login(user):
        with app.test_request_context(environ_base=client.environ_base):
            ident = _create_identifier()
        with client.session_transaction() as sess:
            sess.clear()
            sess["_user_id"] = user.get_id()
            sess["_fresh"] = True
            sess["_id"] = ident
        return client
    return _login


def jpeg_bytes(size=(1200, 900), exif_gps=False) -> io.BytesIO:
    from PIL import Image
    img = Image.new("RGB", size, (180, 120, 70))
    buf = io.BytesIO()
    kwargs = {}
    if exif_gps:
        exif = Image.Exif()
        exif[0x8825] = {1: "N", 2: (52.0, 5.0, 0.0)}  # GPSInfo
        exif[0x010F] = "PhoneMaker"
        kwargs["exif"] = exif
    img.save(buf, "JPEG", **kwargs)
    buf.seek(0)
    return buf
