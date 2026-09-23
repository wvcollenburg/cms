"""Local file storage behind a small interface (§5), laid out like the STRATO web root:
media/<space-id>/... for spaces and media/site/... for the front section.

Hidden spaces' folders move out of the web root (§10a) so Apache can't serve them.
"""
import os
import shutil
from pathlib import Path

from flask import current_app


def _abs(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else Path(current_app.root_path).parent / p


def media_root() -> Path:
    return _abs(current_app.config["MEDIA_ROOT"])


def hidden_root() -> Path:
    return _abs(current_app.config["PRIVATE_ROOT"]) / "hidden-media"


def owner_folder(owner_type: str, owner_id: int) -> str:
    return str(owner_id) if owner_type == "space" else "site"


def save(key: str, data: bytes) -> None:
    path = media_root() / key
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def delete(key: str) -> None:
    for root in (media_root(), hidden_root()):
        (root / key).unlink(missing_ok=True)


def resolve(key: str) -> Path | None:
    """Absolute path of a *public* file, or None. Never serves from the hidden area."""
    root = media_root().resolve()
    path = (root / key).resolve()
    if root not in path.parents or not path.is_file():
        return None
    return path


def hide_space(space_id: int) -> None:
    src = media_root() / str(space_id)
    if src.exists():
        dst = hidden_root() / str(space_id)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            shutil.rmtree(dst)
        shutil.move(str(src), str(dst))


def restore_space(space_id: int) -> None:
    src = hidden_root() / str(space_id)
    if src.exists():
        dst = media_root() / str(space_id)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            shutil.rmtree(dst)
        shutil.move(str(src), str(dst))
