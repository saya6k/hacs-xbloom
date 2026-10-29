"""Machine photos cached by HA (machine_photo.py) so the panel works offline.

The panel loads its photo from HA, never the internet. HA keeps the server
cover per colour code and version, and the store photo per colour, in its
cache directory; once cached, both are served with no network at all.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.xbloom import machine_photo
from custom_components.xbloom.coordinator.connection import ConnectionMixin

SERIAL = "J15A04B4CV030"
PNG, PNG_END = b"\x89PNG\r\n\x1a\n", b"IEND\xaeB`\x82"
GOLD, COVER, COVER1, COVER2 = (
    PNG + tag + PNG_END for tag in (b"gold", b"cover", b"cover1", b"cover2")
)
BLACK = b"RIFF" + (9).to_bytes(4, "little") + b"WEBPblack"


@pytest.fixture
def hass(tmp_path):
    async def run(func, *args):
        return func(*args)

    return SimpleNamespace(
        config=SimpleNamespace(cache_path=lambda *p: str(tmp_path.joinpath(*p))),
        async_add_executor_job=run,
    )


@pytest.fixture
def downloads(monkeypatch):
    """URL -> bytes the fake network serves; anything else fails (offline)."""
    served: dict[str, bytes] = {}
    fetched: list[str] = []

    async def fake_download(hass, url):
        fetched.append(url)
        return served.get(url)

    monkeypatch.setattr(machine_photo, "_download", fake_download)
    return SimpleNamespace(served=served, fetched=fetched)


def _store_url(color):
    return f"{machine_photo.STORE_PHOTO_CDN}{machine_photo.STORE_PHOTOS[color]}?width=720"


def _read(hass, code="04", color="sage_green_gold"):
    return asyncio.run(machine_photo.async_read_photo(hass, code, color))


def test_store_photo_is_cached_then_served_offline(hass, downloads):
    downloads.served[_store_url("sage_green_gold")] = GOLD
    assert asyncio.run(machine_photo.async_cache_store_photo(hass, "sage_green_gold"))
    downloads.served.clear()  # offline from here on
    assert _read(hass) == (GOLD, "image/png")


def test_unknown_colour_uses_the_black_store_photo(hass, downloads):
    downloads.served[_store_url("midnight_black")] = BLACK
    assert _read(hass, code="06", color=None) == (BLACK, "image/webp")


def test_nothing_cached_and_offline_is_none(hass, downloads):
    assert _read(hass) is None


def test_cover_wins_over_the_store_photo_and_keeps_the_newest(hass, downloads):
    downloads.served[_store_url("sage_green_gold")] = GOLD
    downloads.served["https://s3/v1.png"] = COVER1
    downloads.served["https://s3/v2.png"] = COVER2
    asyncio.run(machine_photo.async_cache_store_photo(hass, "sage_green_gold"))
    assert asyncio.run(machine_photo.async_cache_cover(hass, "04", "https://s3/v1.png", 1))
    assert _read(hass) == (COVER1, "image/png")
    assert asyncio.run(machine_photo.async_cache_cover(hass, "04", "https://s3/v2.png", 2))
    assert _read(hass) == (COVER2, "image/png")
    # The older version is dropped once the new one is saved.
    names = sorted(p.name for p in machine_photo.photo_dir(hass).iterdir())
    assert names == ["cover_04_v2.img", "store_sage_green_gold.img"]


def test_a_cached_cover_version_is_not_downloaded_again(hass, downloads):
    downloads.served["https://s3/v1.png"] = COVER1
    asyncio.run(machine_photo.async_cache_cover(hass, "04", "https://s3/v1.png", 1))
    asyncio.run(machine_photo.async_cache_cover(hass, "04", "https://s3/v1.png", 1))
    assert downloads.fetched == ["https://s3/v1.png"]


def test_unsafe_colour_code_is_never_a_file_name(hass, downloads):
    downloads.served["https://s3/x.png"] = b"x"
    assert not asyncio.run(machine_photo.async_cache_cover(hass, "./", "https://s3/x.png", 1))
    assert downloads.fetched == []


def test_image_type_trusts_bytes_not_headers():
    """S3 serves covers as application/octet-stream and Shopify serves PNG
    for a .webp name, so only the magic bytes decide."""
    assert machine_photo.image_type(GOLD) == "image/png"
    assert machine_photo.image_type(BLACK) == "image/webp"
    assert machine_photo.image_type(b"\xff\xd8\xff\xe0jpeg\xff\xd9") == "image/jpeg"
    assert machine_photo.image_type(b"<html>error page</html>") is None


def test_image_type_rejects_a_truncated_image():
    """Live 2026-10-29: the cached black store photo was the first 8 KiB of
    a 720x720 PNG, and the panel drew only its top rows."""
    assert machine_photo.image_type(GOLD[:-3]) is None
    assert machine_photo.image_type(BLACK[:-1]) is None
    assert machine_photo.image_type(b"\xff\xd8\xff\xe0jpeg") is None


def test_a_truncated_cached_photo_is_downloaded_again(hass, downloads):
    path = machine_photo.photo_dir(hass) / "store_sage_green_gold.img"
    path.parent.mkdir(parents=True)
    path.write_bytes(GOLD[:8])
    downloads.served[_store_url("sage_green_gold")] = GOLD
    assert _read(hass) == (GOLD, "image/png")
    assert path.read_bytes() == GOLD


def test_download_reads_every_chunk(hass, monkeypatch):
    """aiohttp's read(n) returns after the first chunk; the whole body must
    be read."""

    class Content:
        async def iter_chunked(self, _size):
            for part in (GOLD[:5], GOLD[5:12], GOLD[12:]):
                yield part

    class Resp:
        status = 200
        content = Content()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    session = MagicMock()
    session.get.return_value = Resp()
    monkeypatch.setattr(machine_photo, "async_get_clientsession", lambda _hass: session)
    assert asyncio.run(machine_photo._download(hass, "https://cdn/x.png")) == GOLD


def _coordinator(hass, cover, configured=True):
    cloud = MagicMock()
    cloud.get_machine_cover = AsyncMock(return_value=cover)
    return SimpleNamespace(
        hass=hass,
        cloud_client=cloud,
        cloud_login_configured=configured,
        async_ensure_cloud_login=AsyncMock(return_value=True),
        _machine_cover=None,
    )


def _refresh(coordinator, serial=SERIAL):
    asyncio.run(ConnectionMixin._async_refresh_machine_photos(coordinator, serial))


def test_refresh_caches_store_photo_and_cover(hass, downloads):
    downloads.served[_store_url("sage_green_gold")] = GOLD
    downloads.served["https://s3/c.png"] = COVER
    coordinator = _coordinator(hass, {"image_url": "https://s3/c.png", "version": 3})
    _refresh(coordinator)
    assert coordinator._machine_cover[:2] == ("04", 3)
    assert ConnectionMixin.machine_cover_version.fget(coordinator) == 3
    assert _read(hass) == (COVER, "image/png")
    _refresh(coordinator)  # fresh check for the same code — no second lookup
    assert coordinator.cloud_client.get_machine_cover.await_count == 1


def test_refresh_without_a_cloud_account_caches_the_store_photo_only(hass, downloads):
    downloads.served[_store_url("sage_green_gold")] = GOLD
    cover = {"image_url": "https://s3/c.png", "version": 1}
    coordinator = _coordinator(hass, cover, configured=False)
    _refresh(coordinator)
    coordinator.cloud_client.get_machine_cover.assert_not_awaited()
    assert ConnectionMixin.machine_cover_version.fget(coordinator) is None
    assert _read(hass) == (GOLD, "image/png")


def test_refresh_offline_keeps_what_is_cached(hass, downloads):
    downloads.served["https://s3/c.png"] = COVER
    asyncio.run(machine_photo.async_cache_cover(hass, "04", "https://s3/c.png", 1))
    downloads.served.clear()
    coordinator = _coordinator(hass, None)  # cover lookup fails offline
    _refresh(coordinator)
    assert coordinator._machine_cover is None
    assert _read(hass) == (COVER, "image/png")


def test_photo_view_serves_the_cached_photo_and_404s_without_one(hass, downloads, monkeypatch):
    from custom_components.xbloom import panel

    coordinator = SimpleNamespace(data={"serial_number": SERIAL})
    monkeypatch.setattr(
        panel, "_coordinator", lambda h, entry_id: coordinator if entry_id == "e1" else None
    )
    request = SimpleNamespace(app={panel.KEY_HASS: hass})
    view = panel.MachinePhotoView()

    assert asyncio.run(view.get(request, "e1")).status == 404  # offline, nothing cached
    downloads.served[_store_url("sage_green_gold")] = GOLD
    resp = asyncio.run(view.get(request, "e1"))
    assert resp.status == 200 and resp.body == GOLD and resp.content_type == "image/png"
    assert asyncio.run(view.get(request, "other")).status == 404
