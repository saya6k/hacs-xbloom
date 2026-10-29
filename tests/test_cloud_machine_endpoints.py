"""Per-machine cloud calls the official app 2.2.5 makes through client-api.

``machine/tuGetInitPouringRadius.tuhtml`` replaced the signed backend-api
Retrofit call 2.2.4 used; ``tuMachineCover.tuhtml`` is new in 2.2.5 and
serves the machine photo the app prefers over its bundled colour images.
Both are encrypted ``tuhtml`` posts that need a login.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from custom_components.xbloom._cloud_client import XBloomCloudClient
from custom_components.xbloom.coordinator.connection import ConnectionMixin

SERIAL = "J15A04B4CV030"


def _client(response, logged_in=True):
    client = XBloomCloudClient(session=None)
    if logged_in:
        client.member_id, client.token = 1, "tok"
    calls = []

    async def fake_post_encrypted(endpoint, payload):
        calls.append((endpoint, payload))
        return response

    client._post_encrypted = fake_post_encrypted
    return client, calls


def test_pour_radius_center_uses_the_tuhtml_endpoint():
    client, calls = _client({"result": "success", "initPouringRadius": 750, "pouringRadius": 760})
    assert asyncio.run(client.get_pour_radius_init_center(SERIAL, 760)) == 750
    endpoint, payload = calls[0]
    assert endpoint == "machine/tuGetInitPouringRadius.tuhtml"
    assert payload["serialNumber"] == SERIAL and payload["pouringRadius"] == 760
    assert payload["memberId"] == 1 and payload["token"] == "tok"


def test_pour_radius_center_needs_login_and_success():
    client, calls = _client({"result": "success", "initPouringRadius": 750}, logged_in=False)
    assert asyncio.run(client.get_pour_radius_init_center(SERIAL, 760)) is None
    assert calls == []
    client, _ = _client({"result": "fail", "resultCode": 2000})
    assert asyncio.run(client.get_pour_radius_init_center(SERIAL, 760)) is None


def test_machine_cover_returns_the_server_photo():
    client, calls = _client({
        "result": "success", "imageUrl": " https://cdn.example/j15-04.png ",
        "productCode": "J15", "sku": "04", "version": 3,
    })
    cover = asyncio.run(client.get_machine_cover(SERIAL))
    assert cover == {"image_url": "https://cdn.example/j15-04.png", "version": 3}
    assert calls[0][0] == "tuMachineCover.tuhtml"
    assert calls[0][1]["serialNumber"] == SERIAL


def test_machine_cover_rejects_another_machine_or_colour():
    """The app's own guard: productCode must be J15 (or empty) and sku the
    serial's colour code (or empty)."""
    base = {"result": "success", "imageUrl": "https://cdn.example/x.png"}
    for extra in ({"productCode": "J20"}, {"sku": "01"}):
        client, _ = _client({**base, **extra})
        assert asyncio.run(client.get_machine_cover(SERIAL)) is None


def test_machine_cover_only_accepts_https_urls():
    for url in ("", "http://cdn.example/x.png", 'javascript:alert(1)'):
        client, _ = _client({"result": "success", "imageUrl": url})
        assert asyncio.run(client.get_machine_cover(SERIAL)) is None


def test_machine_cover_needs_login():
    client, calls = _client({"result": "success"}, logged_in=False)
    assert asyncio.run(client.get_machine_cover(SERIAL)) is None
    assert calls == []


def _coordinator(cover, configured=True):
    cloud = MagicMock()
    cloud.get_machine_cover = AsyncMock(return_value=cover)
    return SimpleNamespace(
        cloud_client=cloud,
        cloud_login_configured=configured,
        async_ensure_cloud_login=AsyncMock(return_value=True),
        _machine_cover=None,
    )


def _refresh(coordinator, serial=SERIAL):
    asyncio.run(ConnectionMixin._async_refresh_machine_cover(coordinator, serial))


def test_cover_refresh_caches_per_colour_code():
    coordinator = _coordinator({"image_url": "https://cdn.example/a.png", "version": 1})
    _refresh(coordinator)
    assert coordinator._machine_cover[:2] == ("04", "https://cdn.example/a.png")
    assert ConnectionMixin.machine_cover_url.fget(coordinator) == "https://cdn.example/a.png"
    _refresh(coordinator)  # fresh cache for the same code — no second call
    assert coordinator.cloud_client.get_machine_cover.await_count == 1
    _refresh(coordinator, "J15A02B4CV030")  # another colour code refetches
    assert coordinator.cloud_client.get_machine_cover.await_count == 2


def test_cover_refresh_skips_without_a_cloud_account():
    coordinator = _coordinator({"image_url": "https://cdn.example/a.png"}, configured=False)
    _refresh(coordinator)
    coordinator.cloud_client.get_machine_cover.assert_not_awaited()
    assert ConnectionMixin.machine_cover_url.fget(coordinator) is None


def test_cover_refresh_failure_keeps_the_colour_photo():
    coordinator = _coordinator(None)
    _refresh(coordinator)
    assert coordinator._machine_cover is None
