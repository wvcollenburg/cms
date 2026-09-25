"""Maker removal (§3a): hide → "no longer active" 404 → restore."""
from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.mail import outbox
from app.models import AuditLog, MakerSpace, SpaceMember, User, utcnow

from .conftest import jpeg_bytes


@pytest.fixture
def setup(make_user, make_space, login):
    jan = make_user("jan")
    web = make_user("web", roles=("webmaster",))
    boss = make_user("boss", roles=("superadmin",))
    s = make_space("jan-hout", [jan])
    return jan, web, boss, s


def _remove(c, space, user, slug=None, reason="left the collective"):
    return c.post(f"/beheer/makers/{space.id}/offline/{user.id}",
                  data={"confirm_slug": slug or space.slug, "reason": reason})


def test_remove_hides_space_and_shows_inactive_page(setup, login, client):
    jan, web, boss, s = setup
    # Jan uploads a photo first, so we can check media stops being served.
    login(jan).post(f"/beheer/space/{s.id}/foto/avatar", data={"file": (jpeg_bytes(), "a.jpg")})
    avatar_key = db.session.get(MakerSpace, s.id).avatar and db.session.get(MakerSpace, s.id).avatar.variants["jpeg"]
    assert client.get(f"/media/{avatar_key}").status_code == 200

    r = _remove(login(web), s, jan)
    assert r.status_code == 302
    s = db.session.get(MakerSpace, s.id)
    assert s.status == "hidden"
    assert abs((s.purge_at - s.hidden_at) - timedelta(days=60)) < timedelta(seconds=1)
    assert s.hidden_by == web.id and s.hide_reason == "left the collective"
    assert not db.session.get(User, jan.id).is_active

    page = client.get("/jan-hout")
    assert page.status_code == 404
    assert b"Jan Hout" in page.data and b"niet meer actief" in page.data
    assert page.headers["X-Robots-Tag"] == "noindex"
    assert client.get("/jan-hout/some-article").status_code == 404
    assert client.get(f"/media/{avatar_key}").status_code == 404
    assert client.get("/makers").data.count(b"jan-hout") == 0

    assert len(outbox) == 1 and outbox[0]["To"] == "jan@example.org"
    assert db.session.query(AuditLog).filter_by(action="space.hidden").count() == 1


def test_inactive_page_follows_visitor_language(setup, login, client):
    jan, web, boss, s = setup
    _remove(login(web), s, jan)
    client.set_cookie("lang", "en", domain="localhost")
    r = client.get("/jan-hout")
    assert b"is no longer active" in r.data and b'lang="en"' in r.data


def test_removal_revokes_sessions(setup, login, app):
    jan, web, boss, s = setup
    jan_client = app.test_client()
    from flask_login.utils import _create_identifier
    with app.test_request_context(environ_base=jan_client.environ_base):
        ident = _create_identifier()
    with jan_client.session_transaction() as sess:
        sess["_user_id"], sess["_fresh"], sess["_id"] = jan.get_id(), True, ident
    assert jan_client.get(f"/beheer/space/{s.id}/").status_code == 200
    _remove(login(web), s, jan)
    assert jan_client.get(f"/beheer/space/{s.id}/").status_code == 302  # back to login


def test_shared_space_stays_live(make_user, make_space, login, client):
    sanne, bo = make_user("sanne"), make_user("bo")
    web = make_user("web", roles=("webmaster",))
    s = make_space("studio-nerf", [sanne, bo])
    _remove(login(web), s, bo)
    s = db.session.get(MakerSpace, s.id)
    assert s.status == "published"
    assert [m.user_id for m in s.members] == [sanne.id]
    assert client.get("/studio-nerf").status_code == 200
    assert outbox == []  # no page went offline


def test_remove_requires_exact_slug_and_reason(setup, login):
    jan, web, boss, s = setup
    c = login(web)
    assert _remove(c, s, jan, slug="jan").status_code == 400
    assert _remove(c, s, jan, reason="").status_code == 400
    assert db.session.get(MakerSpace, s.id).status == "published"


def test_cannot_remove_self_or_superadmin(make_user, make_space, login):
    web = make_user("web", roles=("webmaster",))
    boss = make_user("boss", roles=("superadmin",))
    s_web = make_space("web-space", [web])
    s_boss = make_space("boss-space", [boss])
    c = login(web)
    _remove(c, s_web, web)
    _remove(c, s_boss, boss)
    assert db.session.get(MakerSpace, s_web.id).status == "published"
    assert db.session.get(MakerSpace, s_boss.id).status == "published"


def test_restore(setup, login, client):
    jan, web, boss, s = setup
    login(jan).post(f"/beheer/space/{s.id}/foto/cover", data={"file": (jpeg_bytes(), "c.jpg")})
    key = db.session.get(MakerSpace, s.id).cover.variants["jpeg"]
    _remove(login(web), s, jan)
    outbox.clear()

    r = login(boss).post(f"/beheer/offline/{s.id}/terugzetten", data={"reason": "paid after all"})
    assert r.status_code == 302
    s = db.session.get(MakerSpace, s.id)
    assert s.status == "draft" and s.purge_at is None and s.hidden_at is None
    assert db.session.get(User, jan.id).is_active
    assert len(outbox) == 1
    # Draft: not public yet, but the files are back in the web root.
    assert client.get("/jan-hout").status_code == 404
    s.status = "published"
    db.session.commit()
    assert client.get(f"/media/{key}").status_code == 200


def test_purge_cap_check_constraint(setup):
    """§3a: purge_at ≤ hidden_at + 365 days is also enforced by the database."""
    _, _, _, s = setup
    now = utcnow()
    s.status, s.hidden_at, s.purge_at = "hidden", now, now + timedelta(days=366)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
    s = db.session.get(MakerSpace, s.id)
    s.status, s.hidden_at, s.purge_at = "hidden", now, now + timedelta(days=300)
    db.session.commit()


def test_membership_survives_for_last_member(setup, login):
    """The last member keeps their membership so a restore loses nothing."""
    jan, web, boss, s = setup
    _remove(login(web), s, jan)
    assert db.session.get(SpaceMember, (s.id, jan.id)) is not None
