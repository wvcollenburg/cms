"""Focal point: the spot every crop of a photo centres on (phone, card, cover)."""
import pytest
from sqlalchemy import select

from app.extensions import db
from app.media import focus_style
from app.models import Block, Media

from .conftest import jpeg_bytes


@pytest.fixture
def photo(make_user, make_space, login):
    """Jan's page with an image block holding one real uploaded photo."""
    jan = make_user("jan")
    s = make_space("jan-hout", [jan])
    c = login(jan)
    c.post(f"/beheer/space/{s.id}/blocks", data={"type": "image"})
    block = db.session.scalar(select(Block).where(Block.type == "image"))
    r = c.post(f"/beheer/space/{s.id}/blocks/{block.id}/upload", data={"file": (jpeg_bytes((1600, 800)), "p.jpg")})
    m = db.session.get(Media, r.json["media_id"])
    block.is_visible = True  # new blocks start hidden until the maker makes them visible
    db.session.commit()
    return dict(jan=jan, space=s, media=m, url=f"/beheer/space/{s.id}/media/{m.id}/focus")


def test_centre_is_the_default_and_adds_no_style(photo):
    m = photo["media"]
    assert (m.focus_x, m.focus_y) == (50, 50)
    assert focus_style(m) == ""


def test_maker_sets_the_focal_point(photo, login, client):
    c = login(photo["jan"])
    page = c.get(photo["url"])
    assert page.status_code == 200 and "focus-picker" in page.get_data(as_text=True)
    next_url = f"/beheer/space/{photo['space'].id}/"
    r = c.post(photo["url"], data={"x": "72.6", "y": "41", "next": next_url})
    assert r.status_code == 302 and r.headers["Location"].endswith(next_url)
    db.session.refresh(photo["media"])
    assert (photo["media"].focus_x, photo["media"].focus_y) == (73, 41)


def test_public_page_crops_around_the_focal_point(photo, login, client):
    c = login(photo["jan"])
    assert "object-position" not in c.get("/jan-hout").get_data(as_text=True)
    c.post(photo["url"], data={"x": "80", "y": "30"})
    # Saving is a content change, so the cached page is replaced right away.
    assert 'style="object-position: 80% 30%"' in c.get("/jan-hout").get_data(as_text=True)


def test_values_are_clamped_and_checked(photo, login):
    c = login(photo["jan"])
    c.post(photo["url"], data={"x": "-20", "y": "250"})
    db.session.refresh(photo["media"])
    assert (photo["media"].focus_x, photo["media"].focus_y) == (0, 100)
    assert c.post(photo["url"], data={"x": "left", "y": "1"}).status_code == 400


def test_only_the_spaces_own_members(photo, make_user, login):
    for user in (make_user("sanne"), make_user("web", roles=("webmaster",)), make_user("boss", roles=("superadmin",))):
        c = login(user)
        assert c.get(photo["url"]).status_code == 403
        assert c.post(photo["url"], data={"x": "1", "y": "1"}).status_code == 403
    db.session.refresh(photo["media"])
    assert (photo["media"].focus_x, photo["media"].focus_y) == (50, 50)


def test_photo_must_belong_to_the_space(photo, make_user, make_space, login):
    sanne = make_user("sanne")
    other = make_space("sanne-nerf", [sanne])
    # Sanne edits her own space, but asks for Jan's photo through it.
    url = f"/beheer/space/{other.id}/media/{photo['media'].id}/focus"
    assert login(sanne).post(url, data={"x": "1", "y": "1"}).status_code == 404


def test_next_must_stay_in_the_admin(photo, login):
    c = login(photo["jan"])
    for bad in ("https://evil.example/", "//evil.example/beheer/", "/makers"):
        r = c.post(photo["url"], data={"x": "10", "y": "10", "next": bad})
        assert r.headers["Location"].endswith(f"/beheer/space/{photo['space'].id}/"), bad


def test_admin_screens_link_to_the_picker(photo, login):
    c = login(photo["jan"])
    block = db.session.scalar(select(Block).where(Block.type == "image"))
    html = c.get(f"/beheer/space/{photo['space'].id}/blocks/{block.id}").get_data(as_text=True)
    assert f"/media/{photo['media'].id}/focus" in html
