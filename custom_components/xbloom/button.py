"""Button entities for XBloom."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import XBloomCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: XBloomCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    async_add_entities(
        [
            XBloomGrindButton(coordinator, entry),
            XBloomPourButton(coordinator, entry),
            XBloomExecuteRecipeButton(coordinator, entry),
            XBloomPauseButton(coordinator, entry),
            XBloomCancelButton(coordinator, entry),
            XBloomVibrateButton(coordinator, entry),
            XBloomTareButton(coordinator, entry),
            XBloomWriteSlotAButton(coordinator, entry),
            XBloomWriteSlotBButton(coordinator, entry),
            XBloomWriteSlotCButton(coordinator, entry),
        ]
    )


class _XBloomButton(CoordinatorEntity[XBloomCoordinator], ButtonEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: XBloomCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)

    @property
    def device_info(self):
        return self.coordinator.device_info


class XBloomGrindButton(_XBloomButton):
    _attr_translation_key = "grind"
    _attr_unique_id = "xbloom_grind"

    async def async_press(self) -> None:
        await self.coordinator.async_grind()


class XBloomPourButton(_XBloomButton):
    _attr_translation_key = "pour"
    _attr_unique_id = "xbloom_pour"

    async def async_press(self) -> None:
        await self.coordinator.async_pour()


class XBloomExecuteRecipeButton(_XBloomButton):
    _attr_translation_key = "execute_recipe"
    _attr_unique_id = "xbloom_execute_recipe"

    async def async_press(self) -> None:
        await self.coordinator.async_execute_recipe()


class XBloomPauseButton(_XBloomButton):
    """Pause / Resume toggle — action depends on machine state.

    Brewing or grinding → pause.  Paused → resume.  Idle → no-op.
    The icon flips between mdi:pause and mdi:play accordingly.
    """

    _attr_translation_key = "pause"
    _attr_unique_id = "xbloom_pause"

    @property
    def icon(self) -> str:
        state = (self.coordinator.data or {}).get("state", "unknown")
        return "mdi:play" if state == "paused" else "mdi:pause"

    async def async_press(self) -> None:
        await self.coordinator.async_pause_resume()


class XBloomCancelButton(_XBloomButton):
    _attr_translation_key = "cancel"
    _attr_unique_id = "xbloom_cancel"

    async def async_press(self) -> None:
        await self.coordinator.async_cancel()


class XBloomVibrateButton(_XBloomButton):
    _attr_translation_key = "vibrate_scale"
    _attr_unique_id = "xbloom_vibrate"

    async def async_press(self) -> None:
        await self.coordinator.async_vibrate_scale()


class XBloomTareButton(_XBloomButton):
    _attr_translation_key = "tare_scale"
    _attr_unique_id = "xbloom_tare"

    async def async_press(self) -> None:
        await self.coordinator.async_tare_scale()


class _XBloomWriteSlotButton(_XBloomButton):
    """Write the currently-selected recipe to one Easy Mode slot."""

    slot_letter: str = ""

    async def async_press(self) -> None:
        await self.coordinator.async_write_easy_slot(self.slot_letter)


class XBloomWriteSlotAButton(_XBloomWriteSlotButton):
    _attr_translation_key = "write_slot_a"
    _attr_unique_id = "xbloom_write_slot_a"
    slot_letter = "A"


class XBloomWriteSlotBButton(_XBloomWriteSlotButton):
    _attr_translation_key = "write_slot_b"
    _attr_unique_id = "xbloom_write_slot_b"
    slot_letter = "B"


class XBloomWriteSlotCButton(_XBloomWriteSlotButton):
    _attr_translation_key = "write_slot_c"
    _attr_unique_id = "xbloom_write_slot_c"
    slot_letter = "C"
