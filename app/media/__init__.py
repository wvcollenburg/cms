"""Image pipeline (§5): the browser already resized to ≤2400 px JPEG; here we check the type,
strip EXIF (incl. GPS), auto-rotate and write WebP variants plus one JPEG fallback.
Pillow is imported lazily so CGI requests that don't upload don't pay for it."""
import io
import uuid

from flask import current_app, url_for
from sqlalchemy import func, select

from app.extensions import db
from app.media import storage
from app.models import Media

WIDTHS = (400, 800, 1600, 2400)
ALLOWED_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
MAX_UPLOAD_BYTES = 15 * 1024 * 1024


class UploadError(ValueError):
    """`code` is one of: too_big, bad_type, quota."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def used_bytes(owner_type: str, owner_id: int) -> int:
    return db.session.scalar(
        select(func.coalesce(func.sum(Media.bytes), 0)).where(
            Media.owner_type == owner_type, Media.owner_id == owner_id
        )
    )


def process_upload(file_storage, owner_type: str, owner_id: int, user, alt_text: str = "") -> Media:
    from PIL import Image, ImageOps  # lazy: only upload requests import Pillow

    raw = file_storage.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise UploadError("too_big")
    try:
        img = Image.open(io.BytesIO(raw))
        fmt = img.format
        img.load()
    except Exception:
        raise UploadError("bad_type")
    if fmt not in ALLOWED_FORMATS:
        raise UploadError("bad_type")

    img = ImageOps.exif_transpose(img)
    has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    img = img.convert("RGBA" if has_alpha else "RGB")
    width, height = img.size

    folder = storage.owner_folder(owner_type, owner_id)
    base = f"{folder}/{uuid.uuid4().hex}"
    files: dict[str, bytes] = {}
    webp: dict[str, str] = {}
    targets = [w for w in WIDTHS if w <= width] or [width]
    for w in targets:
        variant = img if w == width else img.resize((w, round(height * w / width)), Image.LANCZOS)
        buf = io.BytesIO()
        variant.save(buf, "WEBP", quality=80, method=4)  # no exif= → metadata is dropped
        key = f"{base}_{w}.webp"
        files[key] = buf.getvalue()
        webp[str(w)] = key

    fallback_w = min(1600, width)
    fb = img if fallback_w == width else img.resize((fallback_w, round(height * fallback_w / width)), Image.LANCZOS)
    if has_alpha:
        flat = Image.new("RGB", fb.size, (255, 255, 255))
        flat.paste(fb, mask=fb.getchannel("A"))
        fb = flat
    buf = io.BytesIO()
    fb.save(buf, "JPEG", quality=82, optimize=True, progressive=True)
    jpeg_key = f"{base}_{fallback_w}.jpg"
    files[jpeg_key] = buf.getvalue()

    total = sum(len(b) for b in files.values())
    if owner_type == "space" and used_bytes(owner_type, owner_id) + total > current_app.config["SPACE_QUOTA_BYTES"]:
        raise UploadError("quota")

    for key, data in files.items():
        storage.save(key, data)

    media = Media(
        owner_type=owner_type, owner_id=owner_id, kind="image", storage_key=base,
        mime=ALLOWED_FORMATS[fmt], width=width, height=height, bytes=total,
        alt_text=alt_text[:300], variants={"webp": webp, "jpeg": jpeg_key},
        uploaded_by=user.id,
    )
    db.session.add(media)
    db.session.flush()
    return media


def delete_media(media: Media) -> None:
    for key in media_keys(media):
        storage.delete(key)
    db.session.delete(media)


def media_keys(media: Media) -> list[str]:
    v = media.variants or {}
    return list((v.get("webp") or {}).values()) + ([v["jpeg"]] if v.get("jpeg") else [])


def get_owned(media_id, owner_type: str, owner_id: int) -> Media | None:
    """Scoped lookup: a bare media id from a form is never trusted (§3)."""
    try:
        media_id = int(media_id)
    except (TypeError, ValueError):
        return None
    return db.session.scalar(
        select(Media).where(Media.id == media_id, Media.owner_type == owner_type, Media.owner_id == owner_id)
    )


# ------------------------------------------------------------ template helpers

def media_url(key: str) -> str:
    return url_for("public.media", key=key)


def srcset(media: Media) -> str:
    webp = (media.variants or {}).get("webp") or {}
    return ", ".join(f"{media_url(k)} {w}w" for w, k in sorted(webp.items(), key=lambda kv: int(kv[0])))


def src(media: Media, width: int = 800) -> str:
    webp = (media.variants or {}).get("webp") or {}
    if not webp:
        return media_url(media.variants["jpeg"])
    best = min(webp, key=lambda w: (int(w) < width, abs(int(w) - width)))
    return media_url(webp[best])


def fallback(media: Media) -> str:
    return media_url(media.variants["jpeg"])
