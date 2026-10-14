"""pod_detected enrichment from XBloom's cloud (tRecipeDetailOfPods.thtml).

40501 carries only the 6-byte tag id (live-captured 2026-10-14: pod
"KR0005", 3-pour recipe card "XB0001"); the machine loads the recipe on
its own. The cloud lookup only adds bean info and the linked recipes, so
it must never cost the user the event: any failure fires it with just the
xid. Fixtures are trimmed from the real responses for those two tags.
"""
from __future__ import annotations

import asyncio

import pytest

from custom_components.xbloom._cloud_client import XBloomCloudClient


def _pour(volume, pattern=2):
    return {
        "volume": volume, "temperature": 93.0, "flowRate": 3.5, "pausing": 8,
        "pattern": pattern, "isEnableVibrationBefore": 2, "isEnableVibrationAfter": 2,
    }


POD_RESPONSE = {
    "result": "success",
    "podsVo": {
        "id": "KR0005", "theName": "Mucho Berry", "subtitle": "MOMOS COFFEE",
        "origin": "Ethiopia 80%, Colombia 20%", "process": "Natural 80%, Washed 20%",
        "varietal": "Mix", "flavor": "Mixed berry, Cherry, Maple syrup, Juicy",
        "introduce": "N/A", "image": "https://example/pod.png", "imagePath": "https://example/pod.jpg",
    },
    "list": [{
        "theName": "Mucho Berry", "isDefault": 1, "cupType": 2, "dose": 15.0,
        "grandWater": 16.0, "grinderSize": 64.0, "rpm": 120,
        "isEnableBypassWater": 2, "bypassVolume": 5.0, "bypassTemp": 40.0,
        "shareRecipeLink": "https://share-h5.xbloom.com/?id=pod",
        "pourList": [_pour(40.0, 3), _pour(50.0, 3), _pour(60.0), _pour(50.0), _pour(40.0, 1)],
    }],
}

CARD_RESPONSE = {
    "result": "success",
    "podsVo": {
        "id": "XB0001", "theName": "Recipe Card", "subtitle": "Brew beyond boundaries",
        "origin": "Brew Beyond Boundaries", "process": "N/A", "varietal": "N/A",
        "flavor": "N/A", "image": "", "imagePath": "https://example/card.jpg",
    },
    "list": [
        {"theName": name, "isDefault": default, "cupType": cup, "dose": 15.0,
         "grandWater": 17.0, "grinderSize": grind, "rpm": 120,
         "shareRecipeLink": f"https://share-h5.xbloom.com/?id={name}",
         "pourList": [_pour(60.0), _pour(65.0), _pour(65.0), _pour(65.0)]}
        for name, default, cup, grind in (
            ("Brew on xPod", 2, 1, 64.0),
            ("Basic brew", 1, 1, 65.0),
            ("Brew on Omni Dripper", 2, 2, 62.0),
        )
    ],
}


def _client(monkeypatch, response):
    client = XBloomCloudClient(session=None)
    calls = []

    async def fake_post_plain(endpoint, payload):
        calls.append((endpoint, payload))
        return response

    monkeypatch.setattr(client, "_post_plain", fake_post_plain)
    return client, calls


def test_pod_lookup_request_is_a_non_scan_lookup(monkeypatch):
    client, calls = _client(monkeypatch, POD_RESPONSE)
    asyncio.run(client.fetch_pod_detail("KR0005"))
    endpoint, payload = calls[0]
    assert endpoint == "tRecipeDetailOfPods.thtml"
    assert payload["xid"] == "KR0005"
    # 1 = "this was a scan" (bumps the pod's scan stats); 2 = plain lookup.
    assert payload["isRefreshScanTime"] == 2


def test_pod_lookup_returns_bean_info_and_recipe(monkeypatch):
    client, _ = _client(monkeypatch, POD_RESPONSE)
    detail = asyncio.run(client.fetch_pod_detail("KR0005"))
    assert detail["name"] == "Mucho Berry"
    assert detail["roaster"] == "MOMOS COFFEE"
    assert detail["origin"] == "Ethiopia 80%, Colombia 20%"
    assert detail["image"] == "https://example/pod.png"
    assert detail["default_recipe"] == "Mucho Berry"
    (recipe,) = detail["recipes"]
    assert recipe["dose_g"] == 15.0 and recipe["ratio"] == 16.0
    assert recipe["grind_size"] == 64 and len(recipe["pours"]) == 5
    assert recipe["share_url"] == "https://share-h5.xbloom.com/?id=pod"


def test_disabled_bypass_drops_its_stale_values(monkeypatch):
    # KR0005 ships bypassVolume 5 / bypassTemp 40 with isEnableBypassWater=2.
    client, _ = _client(monkeypatch, POD_RESPONSE)
    (recipe,) = asyncio.run(client.fetch_pod_detail("KR0005"))["recipes"]
    assert recipe["bypass_volume"] == 0
    assert recipe["bypass_temperature"] == 0


def test_recipe_card_omits_na_fields_and_lists_every_recipe(monkeypatch):
    client, _ = _client(monkeypatch, CARD_RESPONSE)
    detail = asyncio.run(client.fetch_pod_detail("XB0001"))
    for field in ("process", "varietal", "flavor"):
        assert field not in detail
    # Empty "image" falls back to imagePath.
    assert detail["image"] == "https://example/card.jpg"
    assert [r["name"] for r in detail["recipes"]] == [
        "Brew on xPod", "Basic brew", "Brew on Omni Dripper",
    ]
    # isDefault == 1, not simply the first entry.
    assert detail["default_recipe"] == "Basic brew"


@pytest.mark.parametrize(
    "response",
    [None, {"result": "fail"}, {"result": "success", "list": [], "podsVo": {}}],
)
def test_pod_lookup_failure_or_unknown_xid_is_none(monkeypatch, response):
    client, _ = _client(monkeypatch, response)
    assert asyncio.run(client.fetch_pod_detail("ZZ9999")) is None
