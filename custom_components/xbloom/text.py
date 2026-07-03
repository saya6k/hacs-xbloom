"""Text entities for XBloom — Easy Mode slot contents (A/B/C).

Each entity shows the recipe HA last wrote to that onboard slot ("none"
if never written — the machine doesn't report slot contents, so
``entry.options["easy_slots"]`` is the only record). Setting a value
writes that recipe to the slot: any local recipe name or uid is
accepted. The slots can't be erased over BLE (only overwritten), so an
empty value / "none" is rejected — see SPEC.md §12 for the packet-capture
follow-up on slot clearing.
"""
from __future__ import annotations

import logging

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import XBloomCoordinator

_LOGGER = logging.getLogger(__name__)

_EMPTY = "none"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: XBloomCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    async_add_entities(
        [XBloomEasySlotText(coordinator, slot) for slot in ("A", "B", "C")]
    )


class XBloomEasySlotText(CoordinatorEntity[XBloomCoordinator], TextEntity):
    _attr_has_entity_name = True
    _attr_native_max = 100

    def __init__(self, coordinator: XBloomCoordinator, slot: str) -> None:
        super().__init__(coordinator)
        self._slot = slot
        self._attr_translation_key = f"easy_slot_{slot.lower()}"
        self._attr_unique_id = f"xbloom_easy_slot_{slot.lower()}"

    @property
    def device_info(self):
        return self.coordinator.device_info

    @property
    def native_value(self) -> str:
        contents = self.coordinator.easy_slot_contents(self._slot)
        return (contents or {}).get("name") or _EMPTY

    @property
    def extra_state_attributes(self) -> dict | None:
        contents = self.coordinator.easy_slot_contents(self._slot)
        if not contents:
            return None
        return {"uid": contents.get("uid")}

    async def async_set_value(self, value: str) -> None:
        value = (value or "").strip()
        if not value or value.lower() == _EMPTY:
            raise HomeAssistantError(
                "Easy Mode slots cannot be cleared over Bluetooth — only "
                "overwritten with another recipe."
            )
        result = await self.coordinator.async_write_easy_slot(
            self._slot, identifier=value
        )
        if not result.get("success"):
            raise HomeAssistantError(
                result.get("message", f"Slot {self._slot} write failed")
            )
        self.async_write_ha_state()
