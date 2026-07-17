"""Tests for __init__._coordinators_for_call.

Hardware-reported 2026-07-17: a real `xbloom.advanced_settings` call with a
real `config_entry_id` failed with "No XBloom machine matched the service
call." Root cause: HA's ConfigEntrySelector has no `multiple` option, so
`call.data["config_entry_id"]` is a bare string, not a list — the old code
did `for eid in entry_ids`, which iterates a string character-by-character,
so no single character ever matched a real config entry id. This broke
every service call that specified a target machine, for every service that
goes through this helper.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("homeassistant.core")

from custom_components.xbloom import _coordinators_for_call
from custom_components.xbloom.const import DATA_COORDINATOR, DOMAIN


def _hass_with_entries(entries: dict):
    return SimpleNamespace(data={DOMAIN: entries})


def test_no_config_entry_id_returns_all_coordinators():
    coord_a, coord_b = object(), object()
    hass = _hass_with_entries(
        {
            "entryA": {DATA_COORDINATOR: coord_a},
            "entryB": {DATA_COORDINATOR: coord_b},
        }
    )
    call = SimpleNamespace(data={})
    result = _coordinators_for_call(hass, call)
    assert set(result) == {coord_a, coord_b}


def test_matching_config_entry_id_returns_that_coordinator():
    coord_a, coord_b = object(), object()
    hass = _hass_with_entries(
        {
            "entryA": {DATA_COORDINATOR: coord_a},
            "entryB": {DATA_COORDINATOR: coord_b},
        }
    )
    call = SimpleNamespace(data={"config_entry_id": "entryB"})
    assert _coordinators_for_call(hass, call) == [coord_b]


def test_config_entry_id_is_treated_as_a_single_id_not_a_list():
    # Regression: a real 26-char ULID-style entry id must not be iterated
    # character-by-character.
    coord = object()
    entry_id = "01KXK8PT32CSRH875VJAYHZAEC"
    hass = _hass_with_entries({entry_id: {DATA_COORDINATOR: coord}})
    call = SimpleNamespace(data={"config_entry_id": entry_id})
    assert _coordinators_for_call(hass, call) == [coord]


def test_unknown_config_entry_id_returns_empty():
    hass = _hass_with_entries({"entryA": {DATA_COORDINATOR: object()}})
    call = SimpleNamespace(data={"config_entry_id": "does-not-exist"})
    assert _coordinators_for_call(hass, call) == []
