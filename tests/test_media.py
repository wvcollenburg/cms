import io

from PIL import Image
from sqlalchemy import select

from app.extensions import db
from app.media import storage
from app.models import Block, Media

from .conftest import jpeg_bytes


def test_gallery_upload_makes_variants_and_strips_exif(make_user, make_space, login, client, app):
    jan = make_user("jan")
    s = make_space("jan-hout", [jan])
    c = login(jan)
    c.post(f"/beheer/space/{s.id}/blocks", data={"type": "gallery"})
    block = db.session.scalar(select(Block).where(Block.type == "gallery"))

    r = c.post(f"/beheer/space/{s.id}/blocks/{block.id}/upload",
               data={"file": (jpeg_bytes((2000, 1500), exif_gps=True), "p.jpg")})
    assert r.status_code == 200 and r.json["ok"]
    m = db.session.get(Media, r.json["media_id"])
    assert sorted(m.variants["webp"], key=int) == ["400", "800", "1600"]
    for key in [*m.variants["webp"].values(), m.variants["jpeg"]]:
        path = storage.media_root() / key
        assert path.is_file() and key.startswith(f"{s.id}/")
        img = Image.open(path)
        assert 0x8825 not in img.getexif() and 0x010F not in img.getexif()
    db.session.refresh(block)
    assert block.data["items"] == [{"media_id": m.id, "caption": ""}]


def test_upload_rejects_non_images(make_user, make_space, login):
    jan = make_user("jan")
    s = make_space("jan-hout", [jan])
    c = login(jan)
    c.post(f"/beheer/space/{s.id}/blocks", data={"type": "image"})
    block = db.session.scalar(select(Block).where(Block.type == "image"))
    r = c.post(f"/beheer/space/{s.id}/blocks/{block.id}/upload",
               data={"file": (io.BytesIO(b"<svg onload=alert(1)>"), "x.svg")})
    assert r.status_code == 400 and not r.json["ok"]
    assert db.session.query(Media).count() == 0


def test_gallery_form_cannot_pull_in_other_spaces_media(make_user, make_space, login):
    jan, sanne = make_user("jan"), make_user("sanne")
    s_jan, s_sanne = make_space("jan-hout", [jan]), make_space("sanne-klei", [sanne])
    cs = login(sanne)
    cs.post(f"/beheer/space/{s_sanne.id}/blocks", data={"type": "gallery"})
    g_sanne = db.session.scalar(select(Block).where(Block.type == "gallery", Block.owner_id == s_sanne.id))
    sanne_media = cs.post(f"/beheer/space/{s_sanne.id}/blocks/{g_sanne.id}/upload",
                          data={"file": (jpeg_bytes(), "p.jpg")}).json["media_id"]

    cj = login(jan)
    cj.post(f"/beheer/space/{s_jan.id}/blocks", data={"type": "gallery"})
    g_jan = db.session.scalar(select(Block).where(Block.type == "gallery", Block.owner_id == s_jan.id))
    cj.post(f"/beheer/space/{s_jan.id}/blocks/{g_jan.id}",
            data={"layout": "grid", "item_id": [str(sanne_media)], "item_caption": ["mine now"]})
    db.session.refresh(g_jan)
    assert g_jan.data["items"] == []


def test_removed_photos_are_deleted(make_user, make_space, login):
    jan = make_user("jan")
    s = make_space("jan-hout", [jan])
    c = login(jan)
    c.post(f"/beheer/space/{s.id}/blocks", data={"type": "gallery"})
    g = db.session.scalar(select(Block).where(Block.type == "gallery"))
    mid = c.post(f"/beheer/space/{s.id}/blocks/{g.id}/upload", data={"file": (jpeg_bytes(), "p.jpg")}).json["media_id"]
    key = db.session.get(Media, mid).variants["jpeg"]
    c.post(f"/beheer/space/{s.id}/blocks/{g.id}",
           data={"layout": "grid", "item_id": [str(mid)], "item_caption": [""], "remove": [str(mid)]})
    assert db.session.get(Media, mid) is None
    assert not (storage.media_root() / key).exists()
