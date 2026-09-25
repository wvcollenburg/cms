"""Block types (§4). Each type has a Pydantic schema that validates `blocks.data` on write,
a form parser, an edit template (admin/blocks/<type>.html) and a public template
(blocks/<type>.html)."""
import re
from dataclasses import dataclass
from typing import Callable, Literal
from urllib.parse import parse_qs, urlparse

import nh3
from flask_babel import lazy_gettext as _l
from pydantic import BaseModel, Field, ValidationError, field_validator

__all__ = ["BLOCK_TYPES", "ValidationError", "sanitize_html", "trix_html", "parse_video_url", "safe_url"]


# ------------------------------------------------------------------ helpers

ALLOWED_TAGS = {"p", "br", "h2", "h3", "strong", "b", "em", "i", "del", "ul", "ol", "li", "a", "blockquote"}


def sanitize_html(html: str) -> str:
    # Trix writes <div> paragraphs and <h1> headings; map them to our allowed set first.
    html = re.sub(r"<(/?)div(\s[^>]*)?>", r"<\1p>", html or "")
    html = re.sub(r"<(/?)h1(\s[^>]*)?>", r"<\1h2>", html)
    clean = nh3.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes={"a": {"href"}},
        url_schemes={"http", "https", "mailto"},
        link_rel="noopener nofollow",
    )
    # Drop <br>s hugging a block's edges and empty blocks at either end: blank lines that
    # earlier round trips through Trix added (see trix_html).
    clean = re.sub(r"(<(p|h2|h3|li|blockquote)>)(\s*<br>)+", r"\1", clean)
    clean = re.sub(r"(\s*<br>)+(</(p|h2|h3|li|blockquote)>)", r"\2", clean)
    clean = re.sub(r"^(\s*<p>\s*</p>)+|(<p>\s*</p>\s*)+$", "", clean.strip())
    return clean


def trix_html(html: str) -> str:
    """Stored HTML back into Trix's own dialect. Trix reads a <p>'s margins as extra blank
    lines, so feeding it <p> adds whitespace on every save."""
    html = re.sub(r"<(/?)p>", r"<\1div>", html or "")
    return re.sub(r"<(/?)h2>", r"<\1h1>", html)


def safe_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith("/") and not url.startswith("//"):
        return url
    if re.match(r"^[\w.+-]+@[\w-]+\.[\w.-]+$", url):
        return "mailto:" + url
    if not re.match(r"^[a-z]+:", url, re.I):
        url = "https://" + url
    parsed = urlparse(url)
    if parsed.scheme in ("http", "https") and parsed.netloc or parsed.scheme == "mailto":
        return url
    raise ValueError("url")


YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def parse_video_url(url: str) -> tuple[str, str, str]:
    """Return (provider, video_id, vimeo_hash) or raise ValueError."""
    p = urlparse(url.strip() if "://" in url else "https://" + url.strip())
    host = (p.hostname or "").removeprefix("www.").removeprefix("m.")
    parts = [s for s in p.path.split("/") if s]
    if host in ("youtube.com", "youtube-nocookie.com", "music.youtube.com"):
        vid = parse_qs(p.query).get("v", [""])[0]
        if not vid and len(parts) >= 2 and parts[0] in ("embed", "shorts", "live", "v"):
            vid = parts[1]
        if YOUTUBE_ID.match(vid or ""):
            return "youtube", vid, ""
    elif host == "youtu.be" and parts and YOUTUBE_ID.match(parts[0]):
        return "youtube", parts[0], ""
    elif host in ("vimeo.com", "player.vimeo.com"):
        nums = [s for s in parts if s.isdigit()]
        if nums:
            idx = parts.index(nums[0])
            h = parse_qs(p.query).get("h", [""])[0] or (parts[idx + 1] if len(parts) > idx + 1 else "")
            return "vimeo", nums[0], h if re.match(r"^[0-9a-f]{6,20}$", h) else ""
    raise ValueError("video")


# ------------------------------------------------------------------ schemas

class TextData(BaseModel):
    html: str = ""

    @field_validator("html")
    @classmethod
    def _clean(cls, v):
        return sanitize_html(v)


class ImageData(BaseModel):
    media_id: int | None = None
    caption: str = Field("", max_length=300)
    link: str = ""

    @field_validator("link")
    @classmethod
    def _link(cls, v):
        return safe_url(v)


class GalleryItem(BaseModel):
    media_id: int
    caption: str = Field("", max_length=300)


class GalleryData(BaseModel):
    layout: Literal["grid", "masonry", "carousel"] = "grid"
    items: list[GalleryItem] = Field(default_factory=list, max_length=200)


class VideoData(BaseModel):
    url: str = ""
    provider: Literal["youtube", "vimeo", ""] = ""
    video_id: str = ""
    vimeo_hash: str = ""
    caption: str = Field("", max_length=300)


SOCIAL_PLATFORMS = ("instagram", "youtube", "tiktok", "facebook", "website", "email")


class SocialLink(BaseModel):
    platform: Literal["instagram", "youtube", "tiktok", "facebook", "website", "email"]
    url: str

    @field_validator("url")
    @classmethod
    def _url(cls, v):
        return safe_url(v)


class SocialData(BaseModel):
    links: list[SocialLink] = Field(default_factory=list, max_length=12)


class CtaData(BaseModel):
    label: str = Field("", max_length=80)
    url: str = ""
    style: Literal["primary", "secondary"] = "primary"

    @field_validator("url")
    @classmethod
    def _url(cls, v):
        return safe_url(v)


# ------------------------------------------------------------------ form parsers
# Each returns a plain dict that is then validated by the schema.

def _text_form(form, current: dict) -> dict:
    return {"html": form.get("html", "")}


def _image_form(form, current: dict) -> dict:
    return {**current, "caption": form.get("caption", "").strip(), "link": form.get("link", "")}


def _gallery_form(form, current: dict) -> dict:
    """Items keep their existing media ids; the form only sends order, captions and removals."""
    known = {i["media_id"]: i for i in current.get("items", [])}
    remove = {int(x) for x in form.getlist("remove") if x.isdigit()}
    items, seen = [], set()
    for mid, caption in zip(form.getlist("item_id"), form.getlist("item_caption")):
        if mid.isdigit() and int(mid) in known and int(mid) not in remove and int(mid) not in seen:
            items.append({"media_id": int(mid), "caption": caption.strip()})
            seen.add(int(mid))
    # Photos uploaded after this form was loaded aren't in it yet: keep them at the end.
    items += [i for mid, i in known.items() if mid not in seen and mid not in remove]
    return {"layout": form.get("layout", "grid"), "items": items}


def _video_form(form, current: dict) -> dict:
    url = form.get("url", "").strip()
    data = {"url": url, "caption": form.get("caption", "").strip(), "provider": "", "video_id": "", "vimeo_hash": ""}
    if url:
        data["provider"], data["video_id"], data["vimeo_hash"] = parse_video_url(url)
    return data


def _social_form(form, current: dict) -> dict:
    links = []
    for platform, url in zip(form.getlist("platform"), form.getlist("url")):
        if url.strip():
            links.append({"platform": platform, "url": url.strip()})
    return {"links": links}


def _cta_form(form, current: dict) -> dict:
    return {"label": form.get("label", "").strip(), "url": form.get("url", ""), "style": form.get("style", "primary")}


@dataclass(frozen=True)
class BlockType:
    key: str
    label: object  # lazy string
    schema: type[BaseModel]
    parse_form: Callable[[dict, dict], dict]
    uses_media: bool = False


BLOCK_TYPES: dict[str, BlockType] = {b.key: b for b in (
    BlockType("text", _l("Text"), TextData, _text_form),
    BlockType("gallery", _l("Photo album"), GalleryData, _gallery_form, uses_media=True),
    BlockType("image", _l("Photo"), ImageData, _image_form, uses_media=True),
    BlockType("video", _l("Video"), VideoData, _video_form),
    BlockType("social", _l("Social media buttons"), SocialData, _social_form),
    BlockType("cta", _l("Button"), CtaData, _cta_form),
)}


def validate(block_type: str, data: dict) -> dict:
    return BLOCK_TYPES[block_type].schema.model_validate(data).model_dump()


def media_ids_in(block_type: str, data: dict) -> set[int]:
    if block_type == "gallery":
        return {i["media_id"] for i in data.get("items", [])}
    if block_type == "image" and data.get("media_id"):
        return {data["media_id"]}
    return set()
