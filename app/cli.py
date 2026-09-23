import io
import math
import random
import shutil
from datetime import timedelta

import click
from flask import current_app
from flask.cli import with_appcontext

from app.extensions import db


def register_cli(app):
    app.cli.add_command(init_db)
    app.cli.add_command(seed_demo)


@click.command("init-db")
@with_appcontext
def init_db():
    """Create tables directly (dev/SQLite only; MariaDB uses `flask db upgrade`)."""
    db.create_all()
    click.echo("Tables created.")


@click.command("seed-demo")
@click.option("--reset", is_flag=True, help="Drop all data and media first.")
@with_appcontext
def seed_demo(reset):
    """Load demo content (§10b): front pages NL/EN, 3 live maker spaces, one hidden, one tombstone."""
    from app.media import storage
    if reset:
        db.drop_all()
        for root in (storage.media_root(), storage.hidden_root()):
            shutil.rmtree(root, ignore_errors=True)
    db.create_all()
    from app.models import User
    if db.session.query(User).count():
        raise click.ClickException("Database isn't empty. Use --reset to start over.")
    _seed()
    click.echo("Demo data loaded. Demo password for all demo users: " + current_app.config["DEMO_PASSWORD"])


# ------------------------------------------------------------------ demo images

def _wood_image(seed: int, base: tuple[int, int, int], size=(1600, 1200)) -> io.BytesIO:
    """A generated wood-grain / glaze texture, so the demo needs no third-party photos."""
    from PIL import Image, ImageDraw, ImageFilter

    rnd = random.Random(seed)
    w, h = size
    img = Image.new("RGB", size, base)
    draw = ImageDraw.Draw(img)
    freq = rnd.uniform(0.004, 0.012)
    for y in range(0, h, 3):
        shade = rnd.randint(-22, 22)
        wobble = [int(18 * math.sin(x * freq + y * 0.01 + seed)) for x in range(0, w + 40, 40)]
        pts = [(i * 40, y + wobble[i]) for i in range(len(wobble))]
        color = tuple(max(0, min(255, c + shade)) for c in base)
        draw.line(pts, fill=color, width=3)
    for _ in range(rnd.randint(1, 3)):  # knots
        cx, cy, r = rnd.randint(100, w - 100), rnd.randint(100, h - 100), rnd.randint(20, 60)
        for k in range(r, 0, -6):
            c = tuple(max(0, v - 40 + k // 3) for v in base)
            draw.ellipse((cx - k * 1.6, cy - k, cx + k * 1.6, cy + k), outline=c, width=3)
    img = img.filter(ImageFilter.GaussianBlur(1.2))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    buf.seek(0)
    return buf


def _upload(owner_type, owner_id, user, seed, base, alt, size=(1600, 1200)):
    from app.media import process_upload
    return process_upload(_wood_image(seed, base, size), owner_type, owner_id, user, alt_text=alt)


# ------------------------------------------------------------------ demo content

def _seed():
    from app.auth.routes import ph
    from app.blocks import validate
    from app.models import (
        Block, MakerSpace, Page, PageTranslation, SiteSetting, SpaceMember, SpaceTombstone, User, UserRole, utcnow,
    )

    now = utcnow()
    pw = ph.hash(current_app.config["DEMO_PASSWORD"])

    def user(key, name, lang="nl", roles=(), active=True):
        u = User(email=f"{key}@demo.example.org", display_name=name, ui_lang=lang, password_hash=pw, is_active=active)
        u.roles = [UserRole(role=r) for r in roles]
        db.session.add(u)
        return u

    jan = user("jan", "Jan de Schaaf")
    sanne = user("sanne", "Sanne Draaijer", lang="en")
    bo = user("bo", "Bo Kleiweg")
    noor = user("noor", "Noor Weverink", roles=("webmaster",))
    sleutel = user("sleutel", "Demo sleutelhouder", roles=("superadmin",))
    pieter = user("pieter", "Pieter Smid", active=False)
    db.session.flush()

    def block(owner_type, owner_id, btype, data, pos, lang=None, visible=True, by=None):
        db.session.add(Block(owner_type=owner_type, owner_id=owner_id, lang=lang, type=btype, position=pos,
                             data=validate(btype, data), is_visible=visible, updated_by=by))

    # --- site settings
    for key, lang, value in [
        ("site_name", "", "Broedplaats de Createur"),
        ("address", "", "Voorbeeldstraat 12, 1234 AB Voorbeeldstad"),
        ("contact_email", "", "info@example.org"),
        ("tagline", "nl", "Een werkplaats vol makers: hout, klei, textiel en metaal."),
        ("tagline", "en", "A workshop full of makers: wood, clay, textiles and metal."),
    ]:
        db.session.add(SiteSetting(key=key, lang=lang, value=value))

    # --- front pages
    def page(slug, nav, order, nl, en):
        p = Page(slug=slug, status="published", show_in_nav=nav, nav_order=order)
        p.translations = [PageTranslation(lang="nl", title=nl[0], meta_description=nl[1])]
        if en:
            p.translations.append(PageTranslation(lang="en", title=en[0], meta_description=en[1]))
        db.session.add(p)
        db.session.flush()
        return p

    home = page("home", False, 0, ("Broedplaats de Createur", "Makers in hout, klei, textiel en metaal."),
                ("Broedplaats de Createur", "Makers in wood, clay, textiles and metal."))
    workshop = _upload("page", home.id, noor, 7, (150, 105, 70), "De werkplaats", size=(2000, 1000))
    block("page", home.id, "text", {"html": (
        "<h2>Welkom bij de Broedplaats</h2><p>Wij zijn een groep makers die samen een werkplaats delen. "
        "Hier maken we meubels, keramiek, textiel en smeedwerk. Kom kijken, of neem contact op met een maker.</p>")},
        1, lang="nl")
    block("page", home.id, "image", {"media_id": workshop.id, "caption": "Onze werkplaats"}, 2, lang="nl")
    block("page", home.id, "cta", {"label": "Bekijk alle makers", "url": "/makers"}, 3, lang="nl")
    block("page", home.id, "text", {"html": (
        "<h2>Welcome to the Broedplaats</h2><p>We are a group of makers sharing one workshop. "
        "We make furniture, ceramics, textiles and ironwork. Come and visit, or get in touch with a maker.</p>")},
        1, lang="en")
    block("page", home.id, "image", {"media_id": workshop.id, "caption": "Our workshop"}, 2, lang="en")
    block("page", home.id, "cta", {"label": "See all makers", "url": "/en/makers"}, 3, lang="en")

    over = page("over", True, 1, ("Over ons", "Wie we zijn en hoe de Broedplaats werkt."),
                ("About us", "Who we are and how the Broedplaats works."))
    block("page", over.id, "text", {"html": (
        "<p>De Broedplaats is in 2026 begonnen in een oude timmerfabriek. Iedere maker heeft een eigen "
        "plek en we delen de grote machines.</p>")}, 1, lang="nl")
    block("page", over.id, "text", {"html": (
        "<p>The Broedplaats started in 2026 in an old carpentry factory. Every maker has their own spot "
        "and we share the big machines.</p>")}, 1, lang="en")

    contact = page("contact", True, 2, ("Contact", "Zo bereik je ons."), None)  # NL only: shows the notice on /en/contact
    block("page", contact.id, "text", {"html": "<p>Mail ons op info@example.org of kom langs op zaterdag.</p>"},
          1, lang="nl")
    block("page", contact.id, "social", {"links": [
        {"platform": "instagram", "url": "https://www.instagram.com/"},
        {"platform": "email", "url": "info@example.org"}]}, 2, lang="nl")

    privacy = page("privacy", False, 3, ("Privacy", "Wat we bewaren en hoe lang."),
                   ("Privacy", "What we store and for how long."))
    block("page", privacy.id, "text", {"html": (
        "<h2>Wat we bewaren</h2><p>Deze website gebruikt geen tracking en geen advertentiecookies. We bewaren "
        "alleen een cookie voor je taalkeuze. Video's laden pas als je erop klikt.</p>"
        "<h2>Als een maker vertrekt</h2><p>Haalt een maker de pagina offline, dan wordt alles na 60 dagen "
        "definitief verwijderd. Kopieën in onze back-ups verdwijnen binnen 30 dagen daarna.</p>")}, 1, lang="nl")
    block("page", privacy.id, "text", {"html": (
        "<h2>What we store</h2><p>This website uses no tracking and no advertising cookies. We only keep a "
        "cookie for your language choice. Videos only load when you click them.</p>"
        "<h2>When a maker leaves</h2><p>When a maker's page goes offline, everything is deleted for good "
        "after 60 days. Copies in our backups disappear within 30 days after that.</p>")}, 1, lang="en")

    # --- maker spaces
    def space(slug, name, members, *, lang="nl", tagline="", discipline="", bio="", accent="#b5562f",
              status="published", order=0, base=(160, 110, 70), seed=1):
        s = MakerSpace(slug=slug, name=name, tagline=tagline, discipline=discipline, bio_html=bio, lang=lang,
                       accent_color=accent, status=status, sort_order=order)
        s.members = [SpaceMember(user=u, role="owner") for u in members]
        db.session.add(s)
        db.session.flush()
        s.avatar_media_id = _upload("space", s.id, members[0], seed, base, name, size=(800, 800)).id
        s.cover_media_id = _upload("space", s.id, members[0], seed + 50, base, name, size=(2400, 900)).id
        return s

    def gallery(s, by, n, base, seed, captions):
        items = [{"media_id": _upload("space", s.id, by, seed + i, tuple(max(0, c - 12 * i) for c in base),
                                      captions[i % len(captions)]).id, "caption": captions[i % len(captions)]}
                 for i in range(n)]
        return {"layout": "grid", "items": items}

    s_jan = space("jan-de-schaaf", "Jan de Schaaf", [jan], tagline="Meubels van massief hout, met de hand gemaakt",
                  discipline="Meubelmaker", accent="#8a5a2b", order=1, base=(170, 120, 75), seed=10,
                  bio="<p>Ik maak tafels, kasten en stoelen van Nederlands hout, met zwaluwstaartverbindingen en zonder schroeven.</p>")
    block("space", s_jan.id, "text", {"html": "<h2>Mijn werk</h2><p>Elk meubel begint bij de boom. Ik werk vooral met eiken, iepen en walnoot uit de buurt.</p>"}, 1, by=jan.id)
    block("space", s_jan.id, "gallery", gallery(s_jan, jan, 6, (175, 125, 80), 20,
                                                ["Eiken tafel", "Wandkast in iep", "Zwaluwstaart", "Krukje", "Walnoten kist", "Detail"]), 2, by=jan.id)
    block("space", s_jan.id, "video", {"url": "https://www.youtube.com/watch?v=M7lc1UVf-VE", "provider": "youtube",
                                       "video_id": "M7lc1UVf-VE", "caption": "Een dag in de werkplaats"}, 3, by=jan.id)
    block("space", s_jan.id, "social", {"links": [
        {"platform": "instagram", "url": "https://www.instagram.com/"},
        {"platform": "website", "url": "https://example.org"},
        {"platform": "email", "url": "jan@example.org"}]}, 4, by=jan.id)
    block("space", s_jan.id, "cta", {"label": "Een meubel laten maken", "url": "mailto:jan@example.org"}, 5, by=jan.id)

    s_klei = space("studio-klei", "Studio Klei", [sanne, bo], lang="en", tagline="Stoneware for everyday use",
                   discipline="Ceramics", accent="#4f6d7a", order=2, base=(120, 140, 150), seed=30,
                   bio="<p>We are Sanne and Bo. We throw and glaze stoneware tableware in small batches.</p>")
    block("space", s_klei.id, "gallery", gallery(s_klei, sanne, 5, (125, 145, 155), 40,
                                                 ["Bowls", "Glaze tests", "Mugs", "The kiln", "Plates"]), 1, by=sanne.id)
    block("space", s_klei.id, "video", {"url": "https://vimeo.com/76979871", "provider": "vimeo",
                                        "video_id": "76979871", "caption": "Throwing a bowl"}, 2, by=bo.id)
    block("space", s_klei.id, "social", {"links": [
        {"platform": "instagram", "url": "https://www.instagram.com/"},
        {"platform": "tiktok", "url": "https://www.tiktok.com/"}]}, 3, by=bo.id)

    s_noor = space("noor-weeft", "Noor Weverink", [noor], tagline="Handgeweven textiel en wandkleden",
                   discipline="Weefster", accent="#8e4b6b", order=3, base=(150, 90, 115), seed=60,
                   bio="<p>Ik weef op een oud getouw met wol en linnen van Nederlandse schapen en vlas.</p>")
    block("space", s_noor.id, "text", {"html": "<p>Op zaterdag geef ik workshops. Neem gerust contact op.</p>"}, 1, by=noor.id)
    block("space", s_noor.id, "gallery", {**gallery(s_noor, noor, 4, (155, 95, 120), 70,
                                                    ["Wandkleed", "Getouw", "Garens", "Detail"]), "layout": "masonry"}, 2, by=noor.id)
    block("space", s_noor.id, "social", {"links": [{"platform": "instagram", "url": "https://www.instagram.com/"}]}, 3, by=noor.id)

    # Hidden (removed 10 days ago) so the "no longer active" page can be shown.
    s_pieter = space("pieter-smid", "Pieter Smid", [pieter], tagline="Smeedwerk", discipline="Smid",
                     accent="#555555", order=4, base=(90, 90, 95), seed=80)
    block("space", s_pieter.id, "text", {"html": "<p>Hekken, haken en messen.</p>"}, 1, by=pieter.id)
    s_pieter.status = "hidden"
    s_pieter.hidden_at = now - timedelta(days=10)
    s_pieter.purge_at = s_pieter.hidden_at + timedelta(days=60)
    s_pieter.hidden_by = noor.id
    s_pieter.hide_reason = "Demo: vertrokken uit het collectief"
    db.session.flush()
    from app.media import storage
    storage.hide_space(s_pieter.id)

    db.session.add(SpaceTombstone(slug="henk-houtwerk", display_name="Henk Houtwerk", purged_at=now - timedelta(days=30),
                                  reserved_until=now + timedelta(days=335), reason_kind="scheduled"))
    db.session.add(SpaceTombstone(slug="oud-atelier", display_name=None, purged_at=now - timedelta(days=5),
                                  reserved_until=now + timedelta(days=360), reason_kind="deletion_request"))
    db.session.commit()
