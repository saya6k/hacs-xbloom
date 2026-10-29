"""Machine photos, cached by Home Assistant so the panel works offline.

Like the official app (which keeps its server cover in ``j15-cover/<code>.png``
and falls back to bundled images), HA downloads each photo once into its
cache directory (``.cache/xbloom/photos``, regenerable, not in backups) and
the panel loads it from HA rather than the internet. Photos are never
bundled — they are XBloom's copyright — only fetched at runtime.

Order served: the server-assigned cover for the serial's colour code
(``tuMachineCover``, needs a cloud login to fetch) → XBloom's store photo for
the serial's colour (black for an unknown code) → nothing (404).
"""
from __future__ import annotations

import logging
from pathlib import Path

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# XBloom's own product shots, one per Studio colour, from their store CDN.
# Same three-quarter view for every colour. Keys match MACHINE_COLORS.
STORE_PHOTO_CDN = "https://cdn.shopify.com/s/files/1/0611/5704/8544/files/"
STORE_PHOTOS = {
    "midnight_black": "xbloom_Studio_Midnight_Black_03.webp",
    "moonlight_white": "Frame_34597300_2dd2d49b-c4db-4846-82c6-58bb66c24332.png",
    "sage_green_green": "Frame_34598241.png",
    "sage_green_gold": "Frame_34598234.png",
    "twilight": "Frame_34598248.png",
    "offline_blue": "xbloomofflinebluestudioproductimage-3.webp",
}
DEFAULT_COLOR = "midnight_black"

_TIMEOUT = aiohttp.ClientTimeout(total=15)
_MAX_BYTES = 8 * 1024 * 1024


def image_type(data: bytes) -> str | None:
    """The image's content type from its magic bytes. Headers can't be
    trusted: the S3 covers come as application/octet-stream, and Shopify
    serves PNG for a .webp file name."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return None


def photo_dir(hass: HomeAssistant) -> Path:
    return Path(hass.config.cache_path(DOMAIN, "photos"))


def _safe_code(code: str | None) -> str | None:
    """A serial's colour code, only if it is safe in a file name."""
    return code if code and code.isalnum() else None


def _store_file(color: str | None) -> str:
    return f"store_{color if color in STORE_PHOTOS else DEFAULT_COLOR}.img"


def _cover_files(directory: Path, code: str) -> list[Path]:
    """Cached covers for a colour code, newest version first."""
    def version(path: Path) -> int:
        try:
            return int(path.stem.rsplit("_v", 1)[1])
        except (IndexError, ValueError):
            return -1

    return sorted(directory.glob(f"cover_{code}_v*.img"), key=version, reverse=True)


async def _download(hass: HomeAssistant, url: str) -> bytes | None:
    try:
        async with async_get_clientsession(hass).get(url, timeout=_TIMEOUT) as resp:
            if resp.status != 200:
                return None
            data = await resp.content.read(_MAX_BYTES + 1)
    except (aiohttp.ClientError, TimeoutError) as exc:
        _LOGGER.debug("Machine photo download failed (%s): %s", url, exc)
        return None
    return data if len(data) <= _MAX_BYTES and image_type(data) else None


def _write(path: Path, data: bytes, stale: list[Path] = ()) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    for old in stale:
        if old != path:
            old.unlink(missing_ok=True)


async def async_cache_store_photo(hass: HomeAssistant, color: str | None) -> bool:
    """Download the store photo for a colour unless it is already cached."""
    path = photo_dir(hass) / _store_file(color)
    if await hass.async_add_executor_job(path.is_file):
        return True
    name = STORE_PHOTOS[color if color in STORE_PHOTOS else DEFAULT_COLOR]
    data = await _download(hass, f"{STORE_PHOTO_CDN}{name}?width=720")
    if data is None:
        return False
    await hass.async_add_executor_job(_write, path, data)
    return True


async def async_cache_cover(
    hass: HomeAssistant, code: str | None, url: str, version: int
) -> bool:
    """Download a server cover unless this version is already cached;
    older versions for the code are removed once the new one is saved."""
    code = _safe_code(code)
    if code is None:
        return False
    directory = photo_dir(hass)
    path = directory / f"cover_{code}_v{int(version)}.img"
    if await hass.async_add_executor_job(path.is_file):
        return True
    data = await _download(hass, url)
    if data is None:
        return False
    stale = await hass.async_add_executor_job(_cover_files, directory, code)
    await hass.async_add_executor_job(_write, path, data, stale)
    return True


def _read(directory: Path, code: str | None, color: str | None) -> tuple[bytes, str] | None:
    candidates = _cover_files(directory, code)[:1] if code else []
    candidates.append(directory / _store_file(color))
    for path in candidates:
        if path.is_file() and (content_type := image_type(data := path.read_bytes())):
            return data, content_type
    return None


async def async_read_photo(
    hass: HomeAssistant, code: str | None, color: str | None
) -> tuple[bytes, str] | None:
    """The best cached photo for a machine as (bytes, content type). With
    nothing cached yet, tries to fetch the store photo first (online)."""
    code = _safe_code(code)
    directory = photo_dir(hass)
    photo = await hass.async_add_executor_job(_read, directory, code, color)
    if photo is None and await async_cache_store_photo(hass, color):
        photo = await hass.async_add_executor_job(_read, directory, code, color)
    return photo
