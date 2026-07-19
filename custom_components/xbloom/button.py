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
            XBloomTareButton(coordinator, entry),
            XBloomEnterScaleModeButton(coordinator, entry),
            XBloomExitScaleModeButton(coordinator, entry),
            XBloomCalibrateGrinderButton(coordinator, entry),
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
    """Two-stage arm/confirm flow (2026-07-18): the first press queues
    the grinder (enter mode, size/speed set, burrs adjust) without
    starting; a second press starts it. Gives the user time to place a
    cup/dripper before the grinder actually runs. See
    ``coordinator._armed_operation``'s docstring for the full design —
    HA button entity only, the execute_recipe service / LLM tools /
    async_grind() itself still act in one call.
    """

    _attr_translation_key = "grind"
    _attr_unique_id = "xbloom_grind"

    @property
    def device_info(self):
        return self.coordinator.grinder_device_info

    async def async_press(self) -> None:
        if self.coordinator._armed_operation == "grind":
            await self.coordinator.async_confirm_grind()
        else:
            await self.coordinator.async_arm_grind()


class XBloomPourButton(_XBloomButton):
    """Two-stage arm/confirm flow — see ``XBloomGrindButton``'s
    docstring; same design, first press sends RD_BREWER_IN (8007) only.
    """

    _attr_translation_key = "pour"
    _attr_unique_id = "xbloom_pour"

    @property
    def device_info(self):
        return self.coordinator.brewer_device_info

    async def async_press(self) -> None:
        if self.coordinator._armed_operation == "pour":
            await self.coordinator.async_confirm_pour()
        else:
            await self.coordinator.async_arm_pour()


class XBloomExecuteRecipeButton(_XBloomButton):
    """Two-stage arm/confirm flow — see ``XBloomGrindButton``'s
    docstring; first press queues the selected recipe (through
    8001/8004 coffee or 4513 tea) without starting it.
    """

    _attr_translation_key = "execute_recipe"
    _attr_unique_id = "xbloom_execute_recipe"

    async def async_press(self) -> None:
        if self.coordinator._armed_operation == "recipe":
            await self.coordinator.async_confirm_recipe()
        else:
            await self.coordinator.async_arm_recipe()


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


class XBloomTareButton(_XBloomButton):
    _attr_translation_key = "tare_scale"
    _attr_unique_id = "xbloom_tare"

    @property
    def device_info(self):
        return self.coordinator.scale_device_info

    async def async_press(self) -> None:
        await self.coordinator.async_tare_scale()


class XBloomEnterScaleModeButton(_XBloomButton):
    _attr_translation_key = "enter_scale_mode"
    _attr_unique_id = "xbloom_enter_scale_mode"

    @property
    def device_info(self):
        return self.coordinator.scale_device_info

    async def async_press(self) -> None:
        await self.coordinator.async_enter_scale_mode()


class XBloomExitScaleModeButton(_XBloomButton):
    _attr_translation_key = "exit_scale_mode"
    _attr_unique_id = "xbloom_exit_scale_mode"

    @property
    def device_info(self):
        return self.coordinator.scale_device_info

    async def async_press(self) -> None:
        await self.coordinator.async_exit_scale_mode()


class XBloomCalibrateGrinderButton(_XBloomButton):
    _attr_translation_key = "calibrate_grinder"
    _attr_unique_id = "xbloom_calibrate_grinder"

    @property
    def device_info(self):
        return self.coordinator.grinder_device_info

    async def async_press(self) -> None:
        await self.coordinator.async_calibrate_grinder()


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
