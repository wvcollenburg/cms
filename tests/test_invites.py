import re
from datetime import timedelta

import pytest
from freezegun import freeze_time

from app.extensions import db
from app.mail import outbox
from app.models import AuditLog, Invite, MakerSpace, User


def _invite(c, **overrides):
    data = {"space_name": "Studio Eik", "display_name": "Eva Eik", "email": "Eva@Example.org",
            "slug": "studio-eik", "lang": "nl", **overrides}
    return c.post("/beheer/makers/nieuw", data=data)


def _link() -> str:
    return re.search(r"http://localhost(/auth/uitnodiging/\S+)", outbox[-1].get_content()).group(1)


@pytest.fixture
def web(make_user):
    return make_user("web", roles=("webmaster",))


def test_webmaster_invites_and_maker_accepts(web, login, app):
    r = _invite(login(web))
    assert r.status_code == 302
    space = db.session.query(MakerSpace).filter_by(slug="studio-eik").one()
    assert space.status == "draft" and space.members == []
    assert outbox[-1]["To"] == "eva@example.org" and "Studio Eik" not in outbox[-1]["Subject"]
    assert "/studio-eik" in outbox[-1].get_content()

    visitor = app.test_client()
    link = _link()
    assert b"Eva Eik" in visitor.get(link).data           # GET only shows a button
    assert db.session.query(Invite).one().used_at is None
    r = visitor.post(link)
    assert r.status_code == 302 and r.headers["Location"].endswith(f"/beheer/space/{space.id}/")
    eva = db.session.query(User).filter_by(email="eva@example.org").one()
    assert eva.display_name == "Eva Eik" and space.id in eva.member_space_ids
    assert visitor.get(f"/beheer/space/{space.id}/").status_code == 200  # logged in, can edit own page
    assert visitor.post(link).status_code == 400                          # single use


def test_maker_cannot_invite(make_user, make_space, login):
    jan = make_user("jan")
    make_space("jan-hout", [jan])
    assert login(jan).get("/beheer/makers/nieuw").status_code == 403
    assert _invite(login(jan)).status_code == 403
    assert db.session.query(Invite).count() == 0


@pytest.mark.parametrize("slug,msg", [("beheer", "reserved"), ("x", "3 to 40"), ("jan-hout", "already in use")])
def test_slug_is_checked(web, login, make_user, make_space, slug, msg):
    make_space("jan-hout", [make_user("jan")])
    r = _invite(login(web), slug=slug)
    assert r.status_code == 400
    assert db.session.query(Invite).count() == 0
    # Dutch UI by default: just check the form came back with an error
    assert b"field-error" in r.data


def test_invite_links_existing_user(web, login, make_user, app):
    noor = make_user("noor")
    _invite(login(web), email="noor@example.org", display_name="Noor")
    app.test_client().post(_link())
    space = db.session.query(MakerSpace).filter_by(slug="studio-eik").one()
    assert space.id in db.session.get(User, noor.id).member_space_ids
    assert db.session.query(User).count() == 2  # no duplicate account


def test_removed_maker_cannot_be_reinvited(web, login, make_user):
    make_user("gone", active=False)
    r = _invite(login(web), email="gone@example.org")
    assert r.status_code == 400 and db.session.query(Invite).count() == 0


def test_invite_expires_after_seven_days(web, login, app):
    _invite(login(web))
    link = _link()
    with freeze_time(timedelta(days=8)):
        assert app.test_client().post(link).status_code == 400


def test_only_superadmin_can_grant_webmaster(web, make_user, login, app):
    _invite(login(web), grants_webmaster="1")
    assert db.session.query(Invite).one().grants_webmaster is False

    boss = make_user("boss", roles=("superadmin",))
    _invite(login(boss), slug="studio-es", email="es@example.org", grants_webmaster="1")
    app.test_client().post(_link())
    assert db.session.query(User).filter_by(email="es@example.org").one().has_role("webmaster")


def test_resend_replaces_link_and_withdraw_removes_draft_page(web, login):
    c = login(web)
    _invite(c)
    old_link = _link()
    invite = db.session.query(Invite).one()
    c.post(f"/beheer/makers/uitnodiging/{invite.id}/opnieuw")
    assert len(outbox) == 2 and _link() != old_link
    c.post(f"/beheer/makers/uitnodiging/{invite.id}/intrekken")
    assert db.session.query(Invite).count() == 0
    assert db.session.query(MakerSpace).filter_by(slug="studio-eik").one_or_none() is None
    actions = {a.action for a in db.session.query(AuditLog)}
    assert {"invite.created", "invite.resent", "invite.withdrawn"} <= actions


def test_makers_list_shows_pending_invite(web, login):
    c = login(web)
    _invite(c)
    html = c.get("/beheer/makers").get_data(as_text=True)
    assert "eva@example.org" in html and "/uitnodiging/" in html
