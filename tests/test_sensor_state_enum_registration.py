"""sensor.state is a SensorDeviceClass.ENUM sensor — HA's own `state`
property raises ValueError if the coordinator ever returns a state string
not in XBloomStateSensor._attr_options.

This actually happened: "calibrating" was added to coordinator._async_update_
data's state-derivation chain (and to the translation files) but never added
to _attr_options, so pressing button.calibrate_grinder crashed the sensor's
async_write_ha_state() on every single coordinator refresh for the whole
~120s calibration window (hardware-reported 2026-07-17).

Reads _attr_options via AST rather than importing XBloomStateSensor and
accessing the attribute directly: recent Home Assistant versions back
`_attr_options` with cached-property descriptor magic (see
homeassistant.helpers.entity's CACHED_PROPERTIES_WITH_ATTR_SET), so
`XBloomStateSensor._attr_options` at the class level returns the property
object, not the list — only a real instance resolves it correctly, and
building one here would need a full coordinator/config-entry fixture this
repo's pure-logic tests don't set up.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path


def _state_sensor_options() -> set[str]:
    path = Path(__file__).parent.parent / "custom_components" / "xbloom" / "sensor.py"
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "XBloomStateSensor":
            for stmt in node.body:
                if (
                    isinstance(stmt, ast.Assign)
                    and len(stmt.targets) == 1
                    and isinstance(stmt.targets[0], ast.Name)
                    and stmt.targets[0].id == "_attr_options"
                ):
                    return {elt.value for elt in stmt.value.elts}
    raise AssertionError("XBloomStateSensor._attr_options not found")


def test_state_options_include_calibrating():
    assert "calibrating" in _state_sensor_options()


def test_state_options_match_translations():
    root = Path(__file__).parent.parent / "custom_components" / "xbloom"
    options = _state_sensor_options()
    for fname in ("strings.json", "translations/en.json", "translations/ko.json"):
        data = json.loads((root / fname).read_text())
        translated = set(data["entity"]["sensor"]["state"]["state"].keys())
        assert translated == options, fname
