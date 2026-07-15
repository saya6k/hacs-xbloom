"""Binary sensor entities for XBloom."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import XBloomCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: XBloomCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    async_add_entities(
        [
            XBloomGrinderRunningBinarySensor(coordinator, entry),
            XBloomBrewerRunningBinarySensor(coordinator, entry),
            XBloomWaterBinarySensor(coordinator, entry),
            XBloomProblemBinarySensor(coordinator, entry),
        ]
    )


class _XBloomBinarySensor(CoordinatorEntity[XBloomCoordinator], BinarySensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: XBloomCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)

    @property
    def device_info(self):
        return self.coordinator.device_info


class XBloomGrinderRunningBinarySensor(_XBloomBinarySensor):
    _attr_translation_key = "grinder_running"
    _attr_unique_id = "xbloom_grinder_running"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    @property
    def device_info(self):
        return self.coordinator.grinder_device_info

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.get("grinder_running"))


class XBloomBrewerRunningBinarySensor(_XBloomBinarySensor):
    _attr_translation_key = "brewer_running"
    _attr_unique_id = "xbloom_brewer_running"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    @property
    def device_info(self):
        return self.coordinator.brewer_device_info

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.get("brewer_running"))


class XBloomWaterBinarySensor(_XBloomBinarySensor):
    """on = water level low/empty (PROBLEM); off = water OK; unknown when offline."""

    _attr_translation_key = "water_level"
    _attr_unique_id = "xbloom_water_level"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self) -> bool | None:
        # Returning None reports the state as "unknown" rather than a
        # potentially stale "no problem"/"problem" reading from the last
        # session. The water level can't be inferred while offline.
        if not self.coordinator.data.get("connected"):
            return None
        return not bool(self.coordinator.data.get("water_level_ok"))


class XBloomProblemBinarySensor(_XBloomBinarySensor):
    """on = the machine has reported an error; off = no error."""

    _attr_translation_key = "problem"
    _attr_unique_id = "xbloom_problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.get("error"))

    @property
    def extra_state_attributes(self) -> dict:
        err = self.coordinator.data.get("error")
        return {"last_error": err} if err else {}
