"""Switch entities for XBloom."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import XBloomCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: XBloomCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    async_add_entities([XBloomConnectionSwitch(coordinator, entry)])


class XBloomConnectionSwitch(CoordinatorEntity[XBloomCoordinator], SwitchEntity):
    """BLE connection toggle — on=connected, off=disconnected."""

    _attr_has_entity_name = True
    _attr_translation_key = "connection"
    _attr_unique_id = "xbloom_connection_switch"

    def __init__(self, coordinator: XBloomCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)

    @property
    def device_info(self) -> DeviceInfo:
        return self.coordinator.device_info

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.get("connected"))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_connect()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_disconnect()
