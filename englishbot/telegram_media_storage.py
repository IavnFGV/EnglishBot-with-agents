from __future__ import annotations

from pathlib import Path

from aiogram.enums.content_type import ContentType
from aiogram_dialog.api.entities import MediaId
from aiogram_dialog.api.protocols import MediaIdStorageProtocol

from .assets import (
    ASSET_TYPE_AUDIO,
    ASSET_TYPE_IMAGE,
    ASSET_TYPE_VOICE,
    TELEGRAM_MEDIA_KIND_AUDIO,
    TELEGRAM_MEDIA_KIND_PHOTO,
    TELEGRAM_MEDIA_KIND_VOICE,
    cache_telegram_file_id,
    find_asset_by_transport_source,
    get_cached_telegram_file_id,
)


CONTENT_TYPE_TO_CACHE_KINDS = {
    ContentType.PHOTO: (ASSET_TYPE_IMAGE, TELEGRAM_MEDIA_KIND_PHOTO),
    ContentType.AUDIO: (ASSET_TYPE_AUDIO, TELEGRAM_MEDIA_KIND_AUDIO),
    ContentType.VOICE: (ASSET_TYPE_VOICE, TELEGRAM_MEDIA_KIND_VOICE),
}


class SqliteTelegramMediaIdStorage(MediaIdStorageProtocol):
    async def get_media_id(
        self,
        path: str | None,
        url: str | None,
        type: ContentType,
    ) -> MediaId | None:
        cache_key = _resolve_cache_key(path=path, url=url, content_type=type)
        if cache_key is None:
            return None
        cached_file_id = get_cached_telegram_file_id(
            int(cache_key["asset_id"]),
            str(cache_key["telegram_media_kind"]),
        )
        if cached_file_id is None:
            return None
        return MediaId(file_id=cached_file_id)

    async def save_media_id(
        self,
        path: str | None,
        url: str | None,
        type: ContentType,
        media_id: MediaId,
    ) -> None:
        cache_key = _resolve_cache_key(path=path, url=url, content_type=type)
        if cache_key is None:
            return
        if not media_id.file_id.strip():
            return
        cache_telegram_file_id(
            int(cache_key["asset_id"]),
            str(cache_key["telegram_media_kind"]),
            media_id.file_id,
        )


def _resolve_cache_key(
    *,
    path: str | None,
    url: str | None,
    content_type: ContentType,
) -> dict[str, object] | None:
    cache_kinds = CONTENT_TYPE_TO_CACHE_KINDS.get(content_type)
    if cache_kinds is None:
        return None
    asset_type, telegram_media_kind = cache_kinds
    asset_row = find_asset_by_transport_source(
        asset_type=asset_type,
        local_path=_normalize_path_for_asset_lookup(path),
        source_url=(str(url).strip() if url else None),
    )
    if asset_row is None:
        return None
    return {
        "asset_id": int(asset_row["id"]),
        "telegram_media_kind": telegram_media_kind,
    }


def _normalize_path_for_asset_lookup(path: str | None) -> str | None:
    if path is None:
        return None
    return str(Path(path).as_posix())


telegram_media_id_storage = SqliteTelegramMediaIdStorage()
