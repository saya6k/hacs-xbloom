"""The Settings options step must persist only the keys that changed.

Hardware-reported 2026-08-24: changing the water source in the options
flow didn't reach the machine. The form always submits all five keys, and
on a fresh entry telemetry_interval / session_timeout live in entry.data
only — so writing them back unchanged put *new* keys into entry.options,
which made __init__.py's update listener see a changed key outside
_NO_RELOAD_OPTION_KEYS and reload the entry (dropping BLE) instead of
taking the in-place path through _handle_unit_options_change. The new
value was persisted but never pushed to the machine.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from custom_components.xbloom.config_flow import XBloomOptionsFlow


def _flow(options: dict) -> XBloomOptionsFlow:
    entry = SimpleNamespace(
        options=dict(options),
        data={
            "mac_address": "AA:BB:CC:DD:EE:FF",
            "telemetry_interval": 5,
            "session_timeout": 60,
        },
    )
    flow = XBloomOptionsFlow(entry)
    flow.flow_id = "test"
    flow.handler = "xbloom"
    flow.context = {}
    return flow


def _submit(flow: XBloomOptionsFlow, **overrides) -> dict:
    user_input = {
        "telemetry_interval": 5,
        "session_timeout": 60,
        "weight_unit": "g",
        "temp_unit": "c",
        "water_source": "tank",
        **overrides,
    }
    return asyncio.run(flow.async_step_settings(user_input))["data"]


def test_water_source_only_edit_writes_only_water_source():
    flow = _flow({})
    options = _submit(flow, water_source="direct")
    assert options == {"water_source": 1}


def test_unchanged_submit_writes_nothing():
    flow = _flow({})
    assert _submit(flow) == {}


def test_other_settings_still_persist_when_changed():
    flow = _flow({})
    options = _submit(flow, session_timeout=0, temp_unit="f")
    assert options == {"session_timeout": 0, "temp_unit": "f"}


def test_existing_options_are_preserved():
    flow = _flow({"recipes": {"Foo": {}}, "water_source": 1})
    options = _submit(flow, water_source="tank")
    assert options == {"recipes": {"Foo": {}}, "water_source": 0}
