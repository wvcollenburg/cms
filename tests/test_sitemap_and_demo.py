"""sitemap.xml (§8) and the demo reset button (§10b)."""
import xml.etree.ElementTree as ET
from datetime import timedelta

from sqlalchemy import select

from app.extensions import db
from app.models import MakerSpace, SpaceTombstone, User, utcnow

NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9", "x": "http://www.w3.org/1999/xhtml"}


def _sitemap(client):
    resp = client.get("/sitemap.xml")
    assert resp.status_code == 200 and resp.mimetype == "application/xml"
    root = ET.fromstring(resp.data)
    return {u.find("s:loc", NS).text: {a.get("hreflang"): a.get("href") for a in u.findall("x:link", NS)}
            for u in root.findall("s:url", NS)}


def test_sitemap_lists_only_what_visitors_can_see(make_user, make_space, make_page, client):
    make_page("home")
    make_page("over")                # NL + EN
    make_page("contact", en=False)   # NL only: /en/contact is the Dutch page with a notice
    make_space("jan-hout", [make_user("jan")])
    make_space("draft-space", [make_user("d")], status="draft")
    make_space("gone", [make_user("g")], status="hidden")
    db.session.add(SpaceTombstone(slug="oud", display_name=None, reserved_until=utcnow() + timedelta(days=1),
                                  reason_kind="deletion_request"))
    db.session.commit()

    urls = _sitemap(client)
    base = "http://localhost"
    assert set(urls) == {
        f"{base}/", f"{base}/en/", f"{base}/makers", f"{base}/en/makers",
        f"{base}/over", f"{base}/en/over", f"{base}/contact", f"{base}/jan-hout",
    }
    assert urls[f"{base}/en/over"] == {"nl": f"{base}/over", "en": f"{base}/en/over"}
    assert urls[f"{base}/contact"] == {} and urls[f"{base}/jan-hout"] == {}


def test_robots_points_to_a_working_sitemap(make_page, client):
    make_page("home")
    robots = client.get("/robots.txt").get_data(as_text=True)
    line = next(l for l in robots.splitlines() if l.startswith("Sitemap: "))
    assert line.endswith("/sitemap.xml")
    assert client.get("/sitemap.xml").status_code == 200


def test_demo_reset_is_demo_only_and_superadmin_only(app, make_user, login):
    boss = make_user("boss", roles=("superadmin",))
    assert login(boss).post("/beheer/demo/reset").status_code == 404  # not a demo
    app.config["DEMO_MODE"] = True
    web = make_user("web", roles=("webmaster",))
    assert login(web).post("/beheer/demo/reset").status_code == 403
    assert db.session.scalar(select(User).where(User.email == "web@example.org")) is not None


def test_demo_reset_restores_the_demo(app, make_user, make_space, login):
    app.config["DEMO_MODE"] = True
    boss = make_user("boss", roles=("superadmin",))
    make_space("tester-mess", [make_user("tester")])
    c = login(boss)
    assert 'action="/beheer/demo/reset"' in c.get("/beheer/").get_data(as_text=True)  # the button

    r = c.post("/beheer/demo/reset")
    assert r.status_code == 302 and r.headers["Location"].endswith("/auth/demo")
    db.session.expire_all()
    assert db.session.scalar(select(MakerSpace).where(MakerSpace.slug == "tester-mess")) is None
    assert db.session.scalar(select(User).where(User.email == "boss@example.org")) is None
    assert db.session.scalar(select(User).where(User.email == "jan@demo.example.org")) is not None
    # The resetting user is logged out: their account no longer exists.
    assert c.get("/beheer/").status_code == 302
