import re
from datetime import timedelta

from freezegun import freeze_time

from app.extensions import db
from app.mail import outbox
from app.models import LoginToken


def _link_from_mail() -> str:
    body = outbox[-1].get_content()
    return re.search(r"http://localhost(/auth/link/\S+)", body).group(1)


def test_magic_link_flow(make_user, client):
    make_user("jan", lang="en")
    r = client.post("/auth/login", data={"email": " JAN@example.org "})
    assert r.status_code == 200
    assert len(outbox) == 1 and "login link" in outbox[0]["Subject"]  # recipient's ui_lang (en)
    link = _link_from_mail()

    # GET only shows a button, so a mail scanner can't use up the token.
    assert client.get(link).status_code == 200
    assert db.session.query(LoginToken).one().used_at is None

    r = client.post(link)
    assert r.status_code == 302 and r.headers["Location"].endswith("/beheer/")
    assert client.get("/beheer/").status_code == 200

    client.post("/auth/logout")
    assert client.post(link).status_code == 400  # single use


def test_magic_link_expires(make_user, client):
    make_user("jan")
    client.post("/auth/login", data={"email": "jan@example.org"})
    link = _link_from_mail()
    with freeze_time(timedelta(minutes=16)):
        assert client.post(link).status_code == 400


def test_unknown_or_inactive_address_gets_same_answer_and_no_mail(make_user, client):
    make_user("gone", active=False)
    a = client.post("/auth/login", data={"email": "nobody@example.org"})
    b = client.post("/auth/login", data={"email": "gone@example.org"})
    assert a.status_code == b.status_code == 200
    assert outbox == []


def test_rate_limit_per_address(make_user, client):
    make_user("jan")
    for _ in range(5):
        client.post("/auth/login", data={"email": "jan@example.org"})
    r = client.post("/auth/login", data={"email": "jan@example.org"}, follow_redirects=True)
    assert "Te veel pogingen" in r.get_data(as_text=True)
    assert len(outbox) == 5


def test_password_login(make_user, client):
    from app.auth.routes import ph
    u = make_user("jan")
    u.password_hash = ph.hash("correct horse battery")
    db.session.commit()
    assert client.post("/auth/password", data={"email": "jan@example.org", "password": "wrong"}).headers["Location"].endswith("/auth/login")
    r = client.post("/auth/password", data={"email": "jan@example.org", "password": "correct horse battery"})
    assert r.headers["Location"].endswith("/beheer/")


def test_demo_login_is_off_outside_demo_mode(client):
    assert client.get("/auth/demo").status_code == 404
    assert client.post("/auth/demo/1").status_code == 404


def test_demo_mode_refuses_non_demo_host(tmp_path):
    import pytest
    from app import create_app
    with pytest.raises(RuntimeError):
        create_app({"DEMO_MODE": True, "BASE_URL": "https://createur.nl", "SQLALCHEMY_DATABASE_URI": "sqlite://"})


def test_next_param_cannot_redirect_offsite(make_user, client):
    make_user("jan")
    client.get("/auth/login?next=//evil.example/")
    client.post("/auth/login", data={"email": "jan@example.org"})
    r = client.post(_link_from_mail())
    assert r.headers["Location"].endswith("/beheer/")
