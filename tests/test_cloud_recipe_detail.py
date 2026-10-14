"""Cloud recipe detail page: hub detail + the official store's bean link.

User request 2026-10-15: clicking a Cloud result should open its detail
(description, bean info, steps) and, for an official recipe, a link to buy
the beans. The hub detail is communityRecipe/recipe/detail (no login); no
XBloom source carries a web purchase link (the app sells in-app), but an
official recipe is named after the bean the store sells ("Legacy" ↔
xbloom.com/products/legacy), so the link is an exact title match.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.xbloom import _cloud_client, panel
from custom_components.xbloom._cloud_client import XBloomCloudClient

# Trimmed from the live response for community recipe 70577 (2026-10-15).
DETAIL_RESPONSE = {
    "code": 200,
    "data": {
        "communityRecipeId": 70577, "recipeName": "Legacy", "official": 1,
        "imageUrl": "https://tbdprodpic.s3.us-east-1.amazonaws.com/20260512/6a02e50967909.png",
        "cupType": "xPod", "grandWater": 16.0, "volume": "240", "userName": "xBloom Official",
        "uploadDate": "2026-03-25", "likesCount": 5000, "process": ["Washed"],
        "type": "Single Origin", "introduce": "Legacy is a throwback name…",
        "origin": ["Ethiopia"], "varietal": ["Catimor · Caturra"], "roast": 3,
        "flavor": ["Chocolate · Hazelnut · Orange"], "dose": 15.0, "grinderSize": 25.0,
        "rpm": 120, "shareRecipeLink": "https://share-h5.xbloom.com/?id=abc",
        "pourList": [
            {"theName": "Bloom", "volume": 60.0, "temperature": 93.0, "pausing": 20, "pattern": 3},
            {"theName": "Pour1", "volume": 55.0, "temperature": 92.0, "pausing": 15, "pattern": 2},
        ],
    },
}


def _client(monkeypatch, response):
    client = XBloomCloudClient(session=None)
    calls = []

    async def fake_post_collective(endpoint, body):
        calls.append((endpoint, body))
        return response

    monkeypatch.setattr(client, "_post_collective", fake_post_collective)
    return client, calls


def test_detail_reads_description_bean_info_and_named_steps(monkeypatch):
    client, calls = _client(monkeypatch, DETAIL_RESPONSE)
    d = asyncio.run(client.fetch_collective_detail(70577))
    assert calls == [("communityRecipe/recipe/detail", {"id": 70577, "type": 1})]
    assert d["name"] == "Legacy" and d["official"] is True
    assert d["introduce"].startswith("Legacy is")
    assert d["origin"] == "Ethiopia" and d["flavor"] == "Chocolate · Hazelnut · Orange"
    assert d["roast"] == 3 and d["type"] == "Single Origin"
    assert d["pours"][0] == {"name": "Bloom", "volume_ml": 60.0, "temperature_c": 93.0,
                             "pause_seconds": 20, "pattern": "circular"}
    assert d["pours"][1]["pattern"] == "spiral"


def test_detail_failure_is_none(monkeypatch):
    for response in (None, {"code": 500}, {"code": 200, "data": None}):
        client, _ = _client(monkeypatch, response)
        assert asyncio.run(client.fetch_collective_detail(1)) is None


class _Resp:
    def __init__(self, payload):
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self, content_type=None):
        return self.payload


class _Session:
    def __init__(self, pages):
        self.pages = pages
        self.gets = 0

    def get(self, url, params=None, headers=None, timeout=None):
        self.gets += 1
        return _Resp({"products": self.pages.get(params["page"], [])})


STORE = {1: [
    {"title": "Legacy", "handle": "legacy"},
    {"title": "BAM - Blackberry and Mint {BLEND}", "handle": "bam-blackberry-and-mint-blend"},
    {"title": "xbloom  Studio", "handle": "xbloom-studio"},
]}


def test_store_link_is_an_exact_title_match():
    session = _Session(STORE)
    client = XBloomCloudClient(session=session)
    assert asyncio.run(client.find_store_product("Legacy")) == "https://xbloom.com/products/legacy"
    assert asyncio.run(client.find_store_product(" legacy ")) == "https://xbloom.com/products/legacy"
    assert asyncio.run(client.find_store_product("xbloom studio")) == "https://xbloom.com/products/xbloom-studio"
    # No fuzzy guessing: a partial or different name gets no link.
    assert asyncio.run(client.find_store_product("Legacy Reserve")) is None
    assert asyncio.run(client.find_store_product("Blackberry")) is None
    assert asyncio.run(client.find_store_product(None)) is None


def test_store_list_is_cached():
    session = _Session(STORE)
    client = XBloomCloudClient(session=session)
    asyncio.run(client.find_store_product("Legacy"))
    first = session.gets
    asyncio.run(client.find_store_product("Legacy"))
    assert session.gets == first  # second lookup served from the cache
    assert first == 2  # page 1, then the empty page 2 ends the walk


def test_store_failure_gives_no_link(monkeypatch):
    class _Broken:
        def get(self, *a, **k):
            raise _cloud_client.aiohttp.ClientError("down")

    client = XBloomCloudClient(session=_Broken())
    assert asyncio.run(client.find_store_product("Legacy")) is None


# ---- panel command


def _run_detail(coordinator, rid=70577):
    from custom_components.xbloom.const import DATA_COORDINATOR, DOMAIN

    hass = MagicMock()
    hass.data = {DOMAIN: {"e1": {DATA_COORDINATOR: coordinator}}}
    conn = MagicMock()
    panel.ws_cloud_detail(hass, conn, {"id": 9, "entry_id": "e1", "community_recipe_id": rid})
    asyncio.run(hass.async_create_background_task.call_args.args[0])
    return conn


def _coordinator(detail, product="https://xbloom.com/products/legacy"):
    looked_up = []

    async def fetch(rid):
        return detail

    async def find(name):
        looked_up.append(name)
        return product

    client = SimpleNamespace(fetch_collective_detail=fetch, find_store_product=find)
    return SimpleNamespace(cloud_client=client), looked_up


def test_official_recipe_gets_the_store_link():
    coordinator, looked_up = _coordinator({"name": "Legacy", "official": True})
    conn = _run_detail(coordinator)
    assert looked_up == ["Legacy"]
    assert conn.send_result.call_args.args[1]["product_url"] == "https://xbloom.com/products/legacy"


def test_community_recipe_gets_no_store_lookup():
    coordinator, looked_up = _coordinator({"name": "Kenya AA", "official": False})
    conn = _run_detail(coordinator)
    assert looked_up == []
    assert "product_url" not in conn.send_result.call_args.args[1]


def test_detail_failure_is_an_error():
    coordinator, _ = _coordinator(None)
    conn = _run_detail(coordinator)
    assert conn.send_error.call_args.args[1] == "fetch_failed"
