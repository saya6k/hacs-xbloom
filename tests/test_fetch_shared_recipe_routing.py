"""Tests for XBloomCloudClient.fetch_shared_recipe's identifier routing.

Hardware-reported 2026-07-18: cloud_import_recipe failed for a bare
community recipe id (just the digits, no `collective.xbloom.com/recipe/`
prefix) — fetch_shared_recipe only recognized the community-recipe-id
shape when embedded in the full collective.xbloom.com URL, so a bare id
fell through to being treated as an opaque share-h5.xbloom.com share id
(a different identifier space entirely — see AGENTS.md/project memory
xbloom-collective-hub-and-backend-api), which the real API rejects.

These tests exercise only the routing decision (which resolution path a
given input takes), not real network I/O: _resolve_collective_link and
_post_plain are monkeypatched to record what they were called with.
"""
from __future__ import annotations

import asyncio

import pytest

from custom_components.xbloom._cloud_client import XBloomCloudClient


def _client() -> XBloomCloudClient:
    return XBloomCloudClient(session=None)


def _patch_collective(monkeypatch, client, share_link="https://share-h5.xbloom.com/?id=abc"):
    calls = []

    async def fake_resolve(community_recipe_id):
        calls.append(community_recipe_id)
        return share_link

    monkeypatch.setattr(client, "_resolve_collective_link", fake_resolve)
    return calls


def _patch_post_plain(monkeypatch, client, result="success"):
    calls = []

    async def fake_post_plain(endpoint, payload):
        calls.append((endpoint, payload))
        return {"result": result, "recipeVo": {}}

    monkeypatch.setattr(client, "_post_plain", fake_post_plain)
    return calls


def test_bare_numeric_id_resolves_as_collective_community_id(monkeypatch):
    client = _client()
    collective_calls = _patch_collective(monkeypatch, client)
    post_calls = _patch_post_plain(monkeypatch, client)

    asyncio.run(client.fetch_shared_recipe("123456"))

    assert collective_calls == ["123456"]
    # Resolved share link's id (?id=abc) must reach RecipeDetail.html, not
    # the raw digits.
    assert post_calls[0][1]["tableIdOfRSA"] == "abc"


def test_full_collective_url_still_resolves_as_before(monkeypatch):
    client = _client()
    collective_calls = _patch_collective(monkeypatch, client)
    _patch_post_plain(monkeypatch, client)

    asyncio.run(
        client.fetch_shared_recipe("https://collective.xbloom.com/recipe/98765")
    )

    assert collective_calls == ["98765"]


def test_share_h5_url_does_not_hit_collective_resolution(monkeypatch):
    client = _client()
    collective_calls = _patch_collective(monkeypatch, client)
    post_calls = _patch_post_plain(monkeypatch, client)

    asyncio.run(
        client.fetch_shared_recipe(
            "https://share-h5.xbloom.com/?id=KmMzhYCe5itq%2FJcqOLhiag%3D%3D"
        )
    )

    assert collective_calls == []
    assert post_calls[0][1]["tableIdOfRSA"] == "KmMzhYCe5itq/JcqOLhiag=="


def test_bare_non_numeric_share_id_does_not_hit_collective_resolution(monkeypatch):
    client = _client()
    collective_calls = _patch_collective(monkeypatch, client)
    post_calls = _patch_post_plain(monkeypatch, client)

    asyncio.run(client.fetch_shared_recipe("KmMzhYCe5itq/JcqOLhiag=="))

    assert collective_calls == []
    assert post_calls[0][1]["tableIdOfRSA"] == "KmMzhYCe5itq/JcqOLhiag=="


def test_collective_resolution_failure_returns_none(monkeypatch):
    client = _client()

    async def fake_resolve(_community_recipe_id):
        return None

    monkeypatch.setattr(client, "_resolve_collective_link", fake_resolve)
    post_calls = _patch_post_plain(monkeypatch, client)

    result = asyncio.run(client.fetch_shared_recipe("123456"))

    assert result is None
    assert post_calls == []  # never reached RecipeDetail.html
