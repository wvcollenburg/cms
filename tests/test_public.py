from datetime import timedelta

import pytest

from app.blocks import parse_video_url, safe_url, sanitize_html, trix_html
from app.extensions import db
from app.models import SlugRedirect, SpaceTombstone, utcnow
from app.slugs import check_space_slug


def test_resolver_order(make_user, make_space, make_page, client):
    make_page("home")
    make_page("over", en=False)
    s = make_space("jan-hout", [make_user("jan")])
    make_space("draft-space", [make_user("d")], status="draft")
    db.session.add(SpaceTombstone(slug="oud", display_name=None, reserved_until=utcnow() + timedelta(days=1),
                                  reason_kind="deletion_request"))
    db.session.add(SlugRedirect(old_slug="jan", target_type="space", target_id=s.id))
    db.session.commit()

    assert client.get("/jan-hout").status_code == 200
    assert client.get("/draft-space").status_code == 404
    tomb = client.get("/oud")
    assert tomb.status_code == 404 and b"niet meer actief" in tomb.data
    assert client.get("/over").status_code == 200
    r = client.get("/jan")
    assert r.status_code == 301 and r.headers["Location"].endswith("/jan-hout")
    assert client.get("/nothing-here").status_code == 404


def test_front_page_languages(make_page, client):
    make_page("home")
    make_page("contact", en=False)
    assert b'lang="nl"' in client.get("/").data
    en = client.get("/en/")
    assert b'lang="en"' in en.data and b'hreflang="en"' in en.data
    fallback = client.get("/en/contact")
    assert fallback.status_code == 200
    assert b"only available in Dutch" in fallback.data


def test_maker_page_uses_space_lang_but_visitor_ui(make_user, make_space, client):
    s = make_space("studio-nerf", [make_user("sanne")])
    s.lang = "en"
    db.session.commit()
    r = client.get("/studio-nerf", headers={"Accept-Language": "nl"})
    assert b'<html lang="en">' in r.data
    assert "Inloggen voor makers" in r.get_data(as_text=True)  # interface follows the visitor


def test_language_cookie(client, make_page):
    make_page("home")
    r = client.get("/_lang/en?next=/en/")
    assert r.status_code == 302 and "lang=en" in r.headers["Set-Cookie"]
    assert client.get("/_lang/en?next=https://evil.example").headers["Location"] == "/"


@pytest.mark.parametrize("slug,error", [
    ("jan", None), ("jan-de-schaaf", None), ("ab", "format"), ("Jan", "format"), ("jan--x", "format"),
    ("-jan", "format"), ("beheer", "reserved"), ("makers", "reserved"), ("a" * 41, "format"),
])
def test_slug_rules(app, slug, error):
    assert check_space_slug(slug) == error


@pytest.mark.parametrize("url,expected", [
    ("https://www.youtube.com/watch?v=M7lc1UVf-VE", ("youtube", "M7lc1UVf-VE", "")),
    ("https://youtu.be/M7lc1UVf-VE?si=abc", ("youtube", "M7lc1UVf-VE", "")),
    ("youtube.com/shorts/M7lc1UVf-VE", ("youtube", "M7lc1UVf-VE", "")),
    ("https://vimeo.com/76979871", ("vimeo", "76979871", "")),
    ("https://vimeo.com/76979871/abcdef1234", ("vimeo", "76979871", "abcdef1234")),
    ("https://player.vimeo.com/video/76979871?h=abc123", ("vimeo", "76979871", "abc123")),
])
def test_video_urls(url, expected):
    assert parse_video_url(url) == expected


@pytest.mark.parametrize("url", ["https://example.org/watch?v=x", "not a url", "https://youtube.com/watch?v=short"])
def test_bad_video_urls(url):
    with pytest.raises(ValueError):
        parse_video_url(url)


def test_sanitize_html():
    dirty = '<div>Hi <script>alert(1)</script><a href="javascript:x()">x</a><img src=x onerror=y></div><h1>Title</h1>'
    clean = sanitize_html(dirty)
    assert "<script" not in clean and "javascript:" not in clean and "<img" not in clean
    assert "<p>Hi" in clean and "<h2>Title</h2>" in clean


def test_trix_round_trip_adds_no_whitespace():
    # What Trix posts; stored HTML goes back into Trix as <div>, so saving again is a no-op.
    posted = "<div>Een<br><br>Twee</div><h1>Kop</h1>"
    stored = sanitize_html(posted)
    assert stored == "<p>Een<br><br>Twee</p><h2>Kop</h2>"
    assert trix_html(stored) == posted
    # Blank lines earlier round trips added are cleaned up on the next save.
    assert sanitize_html("<div><br>Een<br><br>Twee<br></div><div><br></div>") == "<p>Een<br><br>Twee</p>"


def test_safe_url():
    assert safe_url("example.org") == "https://example.org"
    assert safe_url("jan@example.org") == "mailto:jan@example.org"
    assert safe_url("/makers") == "/makers"
    with pytest.raises(ValueError):
        safe_url("javascript:alert(1)")


def test_video_is_click_to_load(make_user, make_space, client):
    from app.models import Block
    s = make_space("jan-hout", [make_user("jan")])
    db.session.add(Block(owner_type="space", owner_id=s.id, type="video", position=2, is_visible=True,
                         data={"url": "x", "provider": "youtube", "video_id": "M7lc1UVf-VE", "vimeo_hash": "", "caption": ""}))
    db.session.commit()
    html = client.get("/jan-hout").get_data(as_text=True)
    assert "<iframe" not in html
    assert "youtube-nocookie.com/embed/M7lc1UVf-VE" in html
