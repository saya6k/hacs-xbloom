"""XBloom Event entities — error & notification."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import XBloomCoordinator

_LOGGER = logging.getLogger(__name__)

# ── Event type definitions ────────────────────────────────────────────────────

ERROR_EVENT_TYPES = [
    "water_shortage",
    "no_beans",
    "abnormal_dose_or_water",
    "abnormal_gear_position",
    # "_cleared" counterparts, synthesized by the coordinator when a
    # latched error condition resolves (see coordinator/state.py's
    # _handle_ble_event). Only water_shortage has a wire-level resolution
    # signal (40522 value=1); the rest clear when the machine demonstrably
    # works again (brewing_started / pour_complete / recipe_complete).
    "water_shortage_cleared",
    "no_beans_cleared",
    "abnormal_dose_or_water_cleared",
    "abnormal_gear_position_cleared",
]

NOTIFICATION_EVENT_TYPES = [
    "grinding_started",
    "grinding_complete",
    "brewing_started",
    "pour_complete",
    "bloom",
    "paused",
    "recipe_complete",
    "tea_soaking",
    "tea_soak_time_changed",
    "tea_resumed",
    "water_refilled",
    "pod_detected",
    "easy_slot_started",
    "grinder_calibration_started",
    "grinder_calibration_progress",
    "grinder_calibration_complete",
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: XBloomCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    async_add_entities([
        XBloomErrorEvent(coordinator, entry),
        XBloomNotificationEvent(coordinator, entry),
    ])


class _XBloomBaseEvent(EventEntity):
    """Base class for XBloom event entities."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: XBloomCoordinator,
        entry: ConfigEntry,
        category: str,
    ) -> None:
        self._coordinator = coordinator
        self._category = category  # "error" | "notification"

    @property
    def device_info(self):
        return self._coordinator.device_info

    async def async_added_to_hass(self) -> None:
        self._coordinator.register_event_listener(self._on_ble_event)

    async def async_will_remove_from_hass(self) -> None:
        self._coordinator.unregister_event_listener(self._on_ble_event)

    @callback
    def _on_ble_event(self, category: str, event_type: str, attributes: dict) -> None:
        if category != self._category:
            return
        self._trigger_event(event_type, dict(attributes))
        self.async_write_ha_state()


class XBloomErrorEvent(_XBloomBaseEvent):
    """Fires when the machine reports an error condition."""

    _attr_translation_key = "error_event"
    _attr_unique_id = "xbloom_event_error"
    _attr_event_types = ERROR_EVENT_TYPES

    def __init__(self, coordinator: XBloomCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "error")


class XBloomNotificationEvent(_XBloomBaseEvent):
    """Fires on machine state transitions (grind complete, brew complete, etc.)."""

    _attr_translation_key = "notification_event"
    _attr_unique_id = "xbloom_event_notification"
    _attr_event_types = NOTIFICATION_EVENT_TYPES

    def __init__(self, coordinator: XBloomCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "notification")
