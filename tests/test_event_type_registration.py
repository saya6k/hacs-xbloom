"""Every event type the client can fire must be registered on its event entity.

HA's EventEntity._trigger_event raises ValueError for an event_type not in
_attr_event_types — so a map entry in _client.py without a matching entry
in event.py's type lists is a runtime error the first time that
notification arrives (this actually happened: "tea_soak_time_changed" was
in _NOTIFICATION_MAP but missing from NOTIFICATION_EVENT_TYPES, so cmd
8113 during a tea brew raised in the event listener).
"""
from __future__ import annotations

import pytest

pytest.importorskip("homeassistant.components.event")

from custom_components.xbloom._client import _ERROR_MAP, _NOTIFICATION_MAP
from custom_components.xbloom.event import ERROR_EVENT_TYPES, NOTIFICATION_EVENT_TYPES


def test_every_notification_map_value_is_registered():
    assert set(_NOTIFICATION_MAP.values()) <= set(NOTIFICATION_EVENT_TYPES)


def test_every_error_map_value_is_registered():
    assert set(_ERROR_MAP.values()) <= set(ERROR_EVENT_TYPES)


def test_directly_fired_event_types_are_registered():
    # Fired from _handle_response outside the maps (the bidirectional
    # 40522 water-tank branch).
    assert "water_refilled" in NOTIFICATION_EVENT_TYPES
    assert "water_shortage" in ERROR_EVENT_TYPES


def test_event_types_have_translations():
    import json
    from pathlib import Path

    root = Path(__file__).parent.parent / "custom_components" / "xbloom"
    for fname in ("strings.json", "translations/en.json", "translations/ko.json"):
        data = json.loads((root / fname).read_text())
        notif = data["entity"]["event"]["notification_event"][
            "state_attributes"]["event_type"]["state"]
        err = data["entity"]["event"]["error_event"][
            "state_attributes"]["event_type"]["state"]
        assert set(NOTIFICATION_EVENT_TYPES) <= set(notif), fname
        assert set(ERROR_EVENT_TYPES) <= set(err), fname
