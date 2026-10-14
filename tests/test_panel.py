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

from custom_components.xbloom import panel

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
    entry = SimpleNamespace(title="Studio", data={"mac_address": "AA:BB"})
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
