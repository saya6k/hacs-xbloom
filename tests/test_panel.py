"""Sidebar panel contract — panel.py's payload and the JS bundle's entity keys.

The panel addresses entities as ``"<platform>.<translation_key>"`` (the map
``xbloom/machines`` builds from the entity registry), so a renamed
translation key would silently blank a control. Pin every key the bundle
references against strings.json.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from custom_components.xbloom import machine_color, panel

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "xbloom"
JS = (PKG / "frontend" / "xbloom-panel.js").read_text()
PLATFORMS = ("binary_sensor", "button", "event", "number", "select", "sensor", "switch", "update")


def test_panel_entity_keys_exist():
    strings = json.loads((PKG / "strings.json").read_text())["entity"]
    pattern = re.compile(rf'"((?:{"|".join(PLATFORMS)})\.[a-z0-9_]+)"')
    keys = set(pattern.findall(JS))
    assert keys, "no entity keys found in the panel bundle"
    missing = sorted(k for k in keys if k.split(".")[1] not in strings.get(k.split(".")[0], {}))
    assert not missing, f"panel references unknown entity keys: {missing}"


def test_panel_registration_constants():
    assert panel.PANEL_ICON == "mdi:coffee-maker"
    assert (PKG / "frontend" / panel._PANEL_FILE).is_file()
    deps = json.loads((PKG / "manifest.json").read_text())["dependencies"]
    for dep in ("frontend", "http", "panel_custom", "websocket_api"):
        assert dep in deps


def test_machine_payload_maps_entities_and_full_recipes():
    entry = SimpleNamespace(title="Studio", data={"mac_address": "AA:BB"}, options={})
    hass = MagicMock()
    hass.config_entries.async_get_entry.return_value = entry
    coordinator = SimpleNamespace(
        recipes={
            "Daily": {"uid": "u1", "pours": [{"volume_ml": 200}]},
            "Gone": None,  # YAML tombstone — never shown
        },
        selected_recipe="Daily",
        mac_address="AA:BB",
        cloud_login_configured=False,
        easy_slot_contents=lambda s: {"uid": "u1", "name": "Daily"} if s == "A" else None,
        data={"serial_number": "J15A02B4CV030"},
    )
    entries = [
        SimpleNamespace(domain="sensor", translation_key="state",
                        entity_id="sensor.xbloom_state", disabled_by=None),
        SimpleNamespace(domain="button", translation_key="grind",
                        entity_id="button.xbloom_grind", disabled_by="user"),
        SimpleNamespace(domain="sensor", translation_key=None,
                        entity_id="sensor.other", disabled_by=None),
    ]
    with patch.object(panel.er, "async_get"), patch.object(
        panel.er, "async_entries_for_config_entry", return_value=entries
    ):
        payload = panel._machine_payload(hass, "entry1", coordinator)

    assert payload["entities"] == {"sensor.state": "sensor.xbloom_state"}
    assert payload["recipes"] == [
        {"uid": "u1", "pours": [{"volume_ml": 200}], "name": "Daily"}
    ]
    assert payload["easy_slots"]["A"] == {"uid": "u1", "name": "Daily"}
    assert payload["easy_slots"]["B"] is None
    assert payload["title"] == "Studio"
    assert payload["mac"] == "AA:BB"
    # Serial "J15A02…" → the app's white-machine code; nothing picked yet.
    assert payload["detected_color"] == "moonlight_white"


def test_color_from_serial_follows_the_official_app():
    """Device.getHomeImageRes: serialNumber[4:6] "02" = white, else black.
    The app knows no other codes, so neither do we."""
    assert panel.color_from_serial("J15A01B4CV030") == "midnight_black"
    assert panel.color_from_serial("J15A02B4CV030") == "moonlight_white"
    assert panel.color_from_serial("J15A07B4CV030") is None
    assert panel.color_from_serial("J15") is None
    assert panel.color_from_serial(None) is None


def test_unmapped_colours_are_placeholders_never_matched():
    """Only 01/02 are known (from the app); the other colours carry no
    code yet, so no serial can resolve to them by accident."""
    known = {c: code for c, code in machine_color.MACHINE_COLOR_CODES.items() if code}
    assert known == {"midnight_black": "01", "moonlight_white": "02"}
    for code in ("00", "03", "04", "05", "06", "99"):
        assert panel.color_from_serial(f"J15A{code}B4CV030") is None


def test_panel_photo_keys_match_machine_colors():
    block = JS.split("const MACHINE_IMAGES = {", 1)[1].split("};", 1)[0]
    keys = re.findall(r"^\s*([a-z_]+):", block, re.M)
    assert tuple(keys) == machine_color.MACHINE_COLORS


def _run_cloud_search(coordinator, msg):
    """Drive ws_cloud_search's coroutine directly (async_response hands it to
    hass.async_create_background_task, captured here)."""
    import asyncio

    from custom_components.xbloom.const import DATA_COORDINATOR, DOMAIN

    hass = MagicMock()
    hass.data = {DOMAIN: {"entry1": {DATA_COORDINATOR: coordinator}}} if coordinator else {}
    connection = MagicMock()
    panel.ws_cloud_search(hass, connection, {"id": 7, "sort": "likes", "page": 1, **msg})
    coro = hass.async_create_background_task.call_args.args[0]
    asyncio.run(coro)
    return connection


def test_cloud_search_passes_filters_and_page():
    seen = {}

    async def search(**kwargs):
        seen.update(kwargs)
        return {"success": True, "list": [{"name": "A"}], "page_index": 2,
                "total_page": 5, "total": 42}

    coordinator = SimpleNamespace(async_search_collective_recipes=search)
    conn = _run_cloud_search(
        coordinator, {"entry_id": "entry1", "keyword": "kenya", "src": "official", "page": 2}
    )
    assert seen == {"keyword": "kenya", "category": None, "src": "official",
                    "sort": "likes", "sort_direction": "desc", "page": 2}
    conn.send_result.assert_called_once_with(
        7, {"recipes": [{"name": "A"}], "page": 2, "total_page": 5, "total": 42}
    )


def test_cloud_search_errors():
    async def failing(**kwargs):
        return {"success": False, "message": "down"}

    conn = _run_cloud_search(
        SimpleNamespace(async_search_collective_recipes=failing), {"entry_id": "entry1"}
    )
    conn.send_error.assert_called_once_with(7, "search_failed", "down")

    conn = _run_cloud_search(None, {"entry_id": "missing"})
    assert conn.send_error.call_args.args[1] == "not_found"


def test_collective_summary_carries_cover_image():
    from custom_components.xbloom._cloud_client import _collective_result_to_summary

    row = {"communityRecipeId": 1, "recipeName": "Legacy",
           "imageUrl": "https://tbdprodpic.s3.us-east-1.amazonaws.com/x.png"}
    assert _collective_result_to_summary(row, {})["image_url"] == row["imageUrl"]
    assert _collective_result_to_summary({}, {})["image_url"] is None
