from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from . import db

TEACHER_CONTENT_IMAGE_DIR = Path("assets/images/teacher-content")


def store_teacher_content_image(
    learning_item_id: int,
    content: bytes,
    *,
    extension: str = ".jpg",
) -> str:
    if not content:
        raise ValueError("image content is required")

    normalized_extension = extension if extension.startswith(".") else f".{extension}"
    asset_dir = Path(db.DB_PATH).resolve().parent / TEACHER_CONTENT_IMAGE_DIR
    asset_dir.mkdir(parents=True, exist_ok=True)
    filename = f"learning-item-{int(learning_item_id)}-{uuid4().hex}{normalized_extension}"
    output_path = asset_dir / filename
    output_path.write_bytes(content)
    return str((TEACHER_CONTENT_IMAGE_DIR / filename).as_posix())
