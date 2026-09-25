"""All tables. MariaDB conventions (D16): utf8mb4, naive UTC DATETIME, no RETURNING,
no partial indexes. SQLite is only used for local dev and tests."""
import secrets
from datetime import datetime, timezone

from flask_login import UserMixin
from sqlalchemy import (
    JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String,
    Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_session_token() -> str:
    return secrets.token_hex(16)


# ---------------------------------------------------------------- users & auth

class User(UserMixin, db.Model):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)  # always lowercased
    password_hash: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(120))
    ui_lang: Mapped[str] = mapped_column(String(2), default="nl")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Rotating this logs the user out everywhere (removal, password change).
    session_token: Mapped[str] = mapped_column(String(32), default=new_session_token)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)

    roles: Mapped[list["UserRole"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    memberships: Mapped[list["SpaceMember"]] = relationship(back_populates="user", cascade="all, delete-orphan")

    def get_id(self):
        return f"{self.id}.{self.session_token}"

    def has_role(self, role: str) -> bool:
        return any(r.role == role for r in self.roles)

    @property
    def is_superadmin(self) -> bool:
        return self.has_role("superadmin")

    @property
    def is_webmaster(self) -> bool:
        return self.has_role("webmaster")

    @property
    def member_space_ids(self) -> set[int]:
        return {m.space_id for m in self.memberships}


class UserRole(db.Model):
    __tablename__ = "user_roles"
    __table_args__ = (CheckConstraint("role IN ('webmaster', 'superadmin')", name="ck_user_roles_role"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(20), primary_key=True)

    user: Mapped[User] = relationship(back_populates="roles")


class LoginToken(db.Model):
    """Magic links: single use, short lived, only the hash is stored."""
    __tablename__ = "login_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)

    user: Mapped[User] = relationship()


# ---------------------------------------------------------------- maker spaces

SPACE_STATUSES = ("draft", "published", "hidden")


class MakerSpace(db.Model):
    __tablename__ = "maker_spaces"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'published', 'hidden')", name="ck_space_status"),
        CheckConstraint("lang IN ('nl', 'en')", name="ck_space_lang"),
        # §3a: postponing is capped at hidden_at + 1 year, enforced in code and in the DB.
        CheckConstraint(
            "purge_at IS NULL OR purge_at <= hidden_at + INTERVAL 365 DAY", name="ck_space_purge_cap"
        ).ddl_if(dialect="mysql"),
        CheckConstraint(
            "purge_at IS NULL OR purge_at <= datetime(hidden_at, '+365 days')", name="ck_space_purge_cap"
        ).ddl_if(dialect="sqlite"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    tagline: Mapped[str] = mapped_column(String(200), default="")
    bio_html: Mapped[str] = mapped_column(Text, default="")
    discipline: Mapped[str] = mapped_column(String(80), default="")
    lang: Mapped[str] = mapped_column(String(2), default="nl")
    accent_color: Mapped[str] = mapped_column(String(7), default="#00709c")
    avatar_media_id: Mapped[int | None] = mapped_column(ForeignKey("media.id", ondelete="SET NULL"))
    cover_media_id: Mapped[int | None] = mapped_column(ForeignKey("media.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(10), default="draft")
    hidden_at: Mapped[datetime | None] = mapped_column(DateTime)
    purge_at: Mapped[datetime | None] = mapped_column(DateTime)
    hidden_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    hide_reason: Mapped[str | None] = mapped_column(String(500))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    members: Mapped[list["SpaceMember"]] = relationship(back_populates="space", cascade="all, delete-orphan")
    avatar: Mapped["Media | None"] = relationship(foreign_keys=[avatar_media_id])
    cover: Mapped["Media | None"] = relationship(foreign_keys=[cover_media_id])

    @property
    def is_live(self) -> bool:
        return self.status == "published"


class SpaceMember(db.Model):
    __tablename__ = "space_members"

    space_id: Mapped[int] = mapped_column(ForeignKey("maker_spaces.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(10), default="owner")

    space: Mapped[MakerSpace] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="memberships")


class SpaceTombstone(db.Model):
    __tablename__ = "space_tombstones"

    slug: Mapped[str] = mapped_column(String(40), primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String(120))  # NULL after a deletion request
    purged_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    reserved_until: Mapped[datetime] = mapped_column(DateTime)
    reason_kind: Mapped[str] = mapped_column(String(20))


class SlugRedirect(db.Model):
    __tablename__ = "slug_redirects"

    old_slug: Mapped[str] = mapped_column(String(40), primary_key=True)
    target_type: Mapped[str] = mapped_column(String(10))  # 'space' | 'page'
    target_id: Mapped[int] = mapped_column(Integer)


# ---------------------------------------------------------------- front section

class Page(db.Model):
    """Front pages. The page with slug 'home' is the front page at / and /en/."""
    __tablename__ = "pages"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    status: Mapped[str] = mapped_column(String(10), default="draft")
    show_in_nav: Mapped[bool] = mapped_column(Boolean, default=False)
    nav_order: Mapped[int] = mapped_column(Integer, default=0)

    translations: Mapped[list["PageTranslation"]] = relationship(back_populates="page", cascade="all, delete-orphan")

    def translation(self, lang: str) -> "PageTranslation | None":
        return next((t for t in self.translations if t.lang == lang), None)


class PageTranslation(db.Model):
    __tablename__ = "page_translations"

    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), primary_key=True)
    lang: Mapped[str] = mapped_column(String(2), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    meta_description: Mapped[str] = mapped_column(String(300), default="")

    page: Mapped[Page] = relationship(back_populates="translations")


class SiteSetting(db.Model):
    __tablename__ = "site_settings"
    __table_args__ = (UniqueConstraint("key", "lang", name="uq_site_setting"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(60))
    lang: Mapped[str] = mapped_column(String(2), default="")  # '' = language independent
    value: Mapped[dict | list | str | None] = mapped_column(JSON)


# ---------------------------------------------------------------- blocks & media

OWNER_TYPES = ("space", "page")


class Block(db.Model):
    """Polymorphic: owner_type 'space' (lang NULL) or 'page' (one block list per lang)."""
    __tablename__ = "blocks"
    __table_args__ = (Index("ix_blocks_owner", "owner_type", "owner_id", "lang", "position"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_type: Mapped[str] = mapped_column(String(10))
    owner_id: Mapped[int] = mapped_column(Integer)
    lang: Mapped[str | None] = mapped_column(String(2))
    type: Mapped[str] = mapped_column(String(20))
    position: Mapped[int] = mapped_column(Integer, default=0)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    is_visible: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class Media(db.Model):
    __tablename__ = "media"
    __table_args__ = (Index("ix_media_owner", "owner_type", "owner_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_type: Mapped[str] = mapped_column(String(10))
    owner_id: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(10), default="image")
    storage_key: Mapped[str] = mapped_column(String(200))  # folder-relative base name
    mime: Mapped[str] = mapped_column(String(40))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    bytes: Mapped[int] = mapped_column(Integer)
    alt_text: Mapped[str] = mapped_column(String(300), default="")
    # {"webp": {"400": "3/abc_400.webp", ...}, "jpeg": "3/abc_1600.jpg"}
    variants: Mapped[dict] = mapped_column(JSON, default=dict)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------------------------------------------------------------- operations

class AuditLog(db.Model):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(60))
    object_type: Mapped[str] = mapped_column(String(20))
    object_id: Mapped[str] = mapped_column(String(60))
    diff: Mapped[dict | None] = mapped_column(JSON)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class RateLimit(db.Model):
    __tablename__ = "rate_limits"

    key: Mapped[str] = mapped_column(String(190), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime)
    count: Mapped[int] = mapped_column(Integer, default=0)


class TaskRun(db.Model):
    __tablename__ = "task_runs"

    task: Mapped[str] = mapped_column(String(40), primary_key=True)
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="never")
    trigger: Mapped[str | None] = mapped_column(String(20))
