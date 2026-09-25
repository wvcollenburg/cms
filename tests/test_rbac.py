"""The permission matrix (§3), one test per row, exercised over HTTP."""
import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import Block, MakerSpace

from .conftest import jpeg_bytes


@pytest.fixture
def world(make_user, make_space, make_page):
    jan = make_user("jan")
    sanne = make_user("sanne")
    web = make_user("web", roles=("webmaster",))
    boss = make_user("boss", roles=("superadmin",))
    s_jan = make_space("jan-hout", [jan])
    s_sanne = make_space("sanne-nerf", [sanne])
    page = make_page("home")
    return dict(jan=jan, sanne=sanne, web=web, boss=boss, s_jan=s_jan, s_sanne=s_sanne, page=page)


def _block(space):
    return db.session.scalar(select(Block).where(Block.owner_type == "space", Block.owner_id == space.id))


def space_requests(space):
    b = _block(space)
    base = f"/beheer/space/{space.id}"
    return [
        ("get", f"{base}/", None),
        ("get", f"{base}/preview", None),
        ("post", f"{base}/blocks", {"type": "text"}),
        ("get", f"{base}/blocks/{b.id}", None),
        ("post", f"{base}/blocks/{b.id}", {"html": "<p>changed</p>"}),
        ("post", f"{base}/blocks/{b.id}/toggle", None),
        ("post", f"{base}/blocks/{b.id}/delete", None),
        ("post", f"/beheer/space/{space.id}/instellingen", {"name": "Hacked"}),
        ("post", f"/beheer/space/{space.id}/zichtbaar", {"visible": "0"}),
    ]


def _call(client, method, url, data):
    return getattr(client, method)(url, data=data or {})


# Row: edit profile, blocks, articles, media in space; publish own content -------------

def test_maker_can_edit_own_space(world, login):
    c = login(world["jan"])
    for method, url, data in space_requests(world["s_jan"]):
        assert _call(c, method, url, data).status_code in (200, 302), url


@pytest.mark.parametrize("who", ["jan", "web", "boss"])
def test_nobody_else_edits_a_space(world, login, who):
    """D3: other makers, webmasters and superadmins all get 403 on Sanne's space."""
    c = login(world[who])
    for method, url, data in space_requests(world["s_sanne"]):
        assert _call(c, method, url, data).status_code == 403, (who, url)
    assert "changed" not in _block(world["s_sanne"]).data["html"]
    assert db.session.get(MakerSpace, world["s_sanne"].id).name != "Hacked"


def test_order_and_upload_are_protected(world, login):
    c = login(world["web"])
    s = world["s_sanne"]
    b = _block(s)
    assert c.post(f"/beheer/space/{s.id}/blocks/order", json={"ids": [b.id]}).status_code == 403
    assert c.post(f"/beheer/space/{s.id}/foto/avatar", data={"file": (jpeg_bytes(), "a.jpg")}).status_code == 403


def test_block_id_is_scoped_to_the_space(world, login):
    """A bare block id is never trusted: Sanne's block via Jan's URL is a 404."""
    c = login(world["jan"])
    b = _block(world["s_sanne"])
    assert c.get(f"/beheer/space/{world['s_jan'].id}/blocks/{b.id}").status_code == 404
    assert c.post(f"/beheer/space/{world['s_jan'].id}/blocks/{b.id}/delete").status_code == 404


def test_hidden_space_cannot_be_edited_even_by_member(world, login):
    s = world["s_jan"]
    s.status = "hidden"
    db.session.commit()
    assert login(world["jan"]).get(f"/beheer/space/{s.id}/").status_code == 403


# Row: edit front pages, news, navigation, site settings -----------------------------

@pytest.mark.parametrize("who,expected", [("jan", 403), ("web", 200), ("boss", 200)])
def test_front_pages(world, login, who, expected):
    c = login(world[who])
    pid = world["page"].id
    assert c.get("/beheer/website").status_code == expected
    assert c.get(f"/beheer/page/{pid}/?lang=nl").status_code == expected
    assert c.get(f"/beheer/page/{pid}/?lang=en").status_code == expected
    r = c.post(f"/beheer/page/{pid}/blocks?lang=en", data={"type": "text"})
    assert r.status_code == (302 if expected == 200 else 403)


# Row: remove a maker -------------------------------------------------------------

@pytest.mark.parametrize("who,expected", [("sanne", 403), ("web", 200), ("boss", 200)])
def test_remove_maker_screen(world, login, who, expected):
    c = login(world[who])
    assert c.get("/beheer/makers").status_code == expected
    assert c.get(f"/beheer/makers/{world['s_jan'].id}/offline/{world['jan'].id}").status_code == expected


# Row: restore, purge now, postpone -----------------------------------------------

@pytest.mark.parametrize("who,expected", [("jan", 403), ("web", 403), ("boss", 200)])
def test_lifecycle_is_superadmin_only(world, login, who, expected):
    c = login(world[who])
    assert c.get("/beheer/offline").status_code == expected
    s = world["s_sanne"]
    s.status = "hidden"
    db.session.commit()
    r = c.post(f"/beheer/offline/{s.id}/terugzetten", data={"reason": "test"})
    assert r.status_code == (302 if expected == 200 else 403)


def test_anonymous_is_sent_to_login(world, client):
    r = client.get(f"/beheer/space/{world['s_jan'].id}/")
    assert r.status_code == 302 and "/auth/login" in r.headers["Location"]
