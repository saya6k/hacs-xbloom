"""Store region for the panel's shop links (the official app's region rule).

jadx 2026-10-15 (BlurSlideHome's shop button): China → the Tmall store,
Korea → xBloom Korea's Cafe24 store, everywhere else → xbloom.com. The panel
follows the same rule, from Home Assistant's country unless the user picks
a region. User request 2026-10-15: xbloom.com hides products from Korea, and
the app lets you choose the country.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.xbloom import panel, stores
from custom_components.xbloom.const import DATA_COORDINATOR, DOMAIN


def test_region_follows_the_apps_rule():
    assert stores.region_for_country("KR") == "kr"
    assert stores.region_for_country("cn") == "cn"
    for country in ("US", "JP", "DE", None, ""):
        assert stores.region_for_country(country) == "global"


def test_a_chosen_region_wins_over_the_country():
    assert stores.effective_region("global", "KR") == "global"
    assert stores.effective_region("kr", "US") == "kr"
    assert stores.effective_region(None, "KR") == "kr"
    assert stores.effective_region("bogus", "KR") == "kr"


def test_store_urls_match_the_app():
    assert stores.STORES["global"]["home"] == "https://xbloom.com"
    assert stores.STORES["kr"]["home"] == "https://xbloomkorea.cafe24.com"
    assert stores.STORES["cn"]["home"] == "https://xbloomcfdq.m.tmall.com/"


def _hass(country="KR", options=None):
    entry = SimpleNamespace(domain=DOMAIN, options=dict(options or {}))
    hass = MagicMock()
    hass.config.country = country
    hass.config_entries.async_get_entry.return_value = entry
    return hass, entry


def test_payload_reports_auto_and_the_effective_store():
    hass, entry = _hass("KR")
    p = panel._store_payload(hass, entry)
    assert p["store_region_setting"] == "auto"
    assert p["store_region"] == "kr" and p["store_auto_region"] == "kr"
    assert p["store"]["home"] == "https://xbloomkorea.cafe24.com"
    hass, entry = _hass("KR", {"store_region": "global"})
    assert panel._store_payload(hass, entry)["store_region"] == "global"


def test_set_store_region_saves_and_auto_clears():
    hass, entry = _hass("US", {"mode": "pro"})
    conn = MagicMock()
    panel.ws_set_store_region(hass, conn, {"id": 1, "entry_id": "e1", "region": "kr"})
    options = hass.config_entries.async_update_entry.call_args.kwargs["options"]
    assert options == {"mode": "pro", "store_region": "kr"}
    entry.options = options
    panel.ws_set_store_region(hass, conn, {"id": 2, "entry_id": "e1", "region": "auto"})
    assert hass.config_entries.async_update_entry.call_args.kwargs["options"] == {"mode": "pro"}


def test_store_region_change_does_not_reload_the_entry():
    from custom_components.xbloom import _NO_RELOAD_OPTION_KEYS

    assert "store_region" in _NO_RELOAD_OPTION_KEYS


def _detail_for(country, options=None, official=True):
    hass, _ = _hass(country, options)
    looked_up = []

    async def fetch(rid):
        return {"name": "Legacy", "official": official}

    async def find(name):
        looked_up.append(name)
        return "https://xbloom.com/products/legacy"

    coordinator = SimpleNamespace(
        cloud_client=SimpleNamespace(fetch_collective_detail=fetch, find_store_product=find)
    )
    hass.data = {DOMAIN: {"e1": {DATA_COORDINATOR: coordinator}}}
    conn = MagicMock()
    panel.ws_cloud_detail(hass, conn, {"id": 3, "entry_id": "e1", "community_recipe_id": 1})
    asyncio.run(hass.async_create_background_task.call_args.args[0])
    return conn.send_result.call_args.args[1], looked_up


def test_global_region_links_the_matching_product():
    detail, looked_up = _detail_for("US")
    assert detail["product_url"] == "https://xbloom.com/products/legacy"
    assert "store_url" not in detail and looked_up == ["Legacy"]


def test_korea_links_the_korean_stores_xpods_instead():
    detail, looked_up = _detail_for("KR")
    assert detail["store_url"] == "https://xbloomkorea.cafe24.com/category/xPod/25/"
    assert detail["store_region"] == "kr"
    assert "product_url" not in detail and looked_up == []


def test_chosen_region_overrides_the_country():
    detail, _ = _detail_for("KR", {"store_region": "global"})
    assert detail["product_url"] == "https://xbloom.com/products/legacy"


def test_machine_payload_carries_the_weight_unit():
    entry = SimpleNamespace(title="Studio", data={"mac_address": "AA"}, options={})
    hass = MagicMock()
    hass.config.country = "KR"
    hass.config_entries.async_get_entry.return_value = entry
    coordinator = SimpleNamespace(
        recipes={}, selected_recipe=None, mac_address="AA", cloud_login_configured=False,
        easy_slot_contents=lambda s: None, data={}, _weight_unit="ml",
    )
    from unittest.mock import patch

    with patch.object(panel.er, "async_get"), patch.object(
        panel.er, "async_entries_for_config_entry", return_value=[]
    ), patch.object(panel, "_machine_serial", return_value=None):
        payload = panel._machine_payload(hass, "e1", coordinator)
    assert payload["weight_unit"] == "ml"
    assert payload["store_region"] == "kr"
