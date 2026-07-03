"""Sensor entities for XBloom."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    EntityCategory,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, UnitOfMass
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
            XBloomStateSensor(coordinator, entry),
            XBloomWeightSensor(coordinator, entry),
            XBloomBrewerTempSensor(coordinator, entry),
            XBloomErrorSensor(coordinator, entry),
            XBloomFirmwareVersionSensor(coordinator, entry),
            XBloomSerialNumberSensor(coordinator, entry),
            *(XBloomEasySlotSensor(coordinator, entry, slot) for slot in ("A", "B", "C")),
        ]
    )


class _XBloomSensor(CoordinatorEntity[XBloomCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: XBloomCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)

    @property
    def device_info(self):
        return self.coordinator.device_info


class XBloomStateSensor(_XBloomSensor):
    _attr_translation_key = "state"
    _attr_unique_id = "xbloom_state"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["unknown", "idle", "grinding", "brewing", "paused", "error", "sleeping"]

    @property
    def native_value(self) -> str:
        return self.coordinator.data.get("state", "unknown")


class XBloomWeightSensor(_XBloomSensor):
    _attr_translation_key = "weight"
    _attr_unique_id = "xbloom_weight"
    _attr_device_class = SensorDeviceClass.WEIGHT
    _attr_native_unit_of_measurement = UnitOfMass.GRAMS

    @property
    def native_value(self) -> float:
        return self.coordinator.data.get("weight", 0.0)


class XBloomBrewerTempSensor(_XBloomSensor):
    _attr_translation_key = "brewer_temperature"
    _attr_unique_id = "xbloom_brewer_temp"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    @property
    def native_value(self) -> float:
        return self.coordinator.data.get("temperature", 0.0)


class XBloomErrorSensor(_XBloomSensor):
    _attr_translation_key = "last_error"
    _attr_unique_id = "xbloom_error"

    @property
    def native_value(self) -> str:
        return self.coordinator.data.get("error") or "none"

    @property
    def icon(self) -> str:
        # Dynamic — error string state is open-ended, so handle in code.
        return "mdi:check-circle" if self.native_value == "none" else "mdi:alert-circle"


class XBloomFirmwareVersionSensor(_XBloomSensor):
    _attr_translation_key = "firmware_version"
    _attr_unique_id = "xbloom_firmware_version"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> str:
        return self.coordinator.data.get("version") or "unknown"


class XBloomSerialNumberSensor(_XBloomSensor):
    _attr_translation_key = "serial_number"
    _attr_unique_id = "xbloom_serial_number"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> str:
        return self.coordinator.data.get("serial_number") or "unknown"


class XBloomEasySlotSensor(_XBloomSensor):
    """Read-only view of what HA last wrote to Easy Mode slot A/B/C.

    Writing a slot is a deliberate action (button / write_recipe_to_easy_slot
    service) rather than something to type into a text box — see the slot
    write tools/services for that. "none" if nothing has been written yet;
    the machine itself never reports slot contents, so
    ``entry.options["easy_slots"]`` is the only record.
    """

    def __init__(self, coordinator: XBloomCoordinator, entry: ConfigEntry, slot: str) -> None:
        super().__init__(coordinator, entry)
        self._slot = slot
        self._attr_translation_key = f"easy_slot_{slot.lower()}"
        self._attr_unique_id = f"xbloom_easy_slot_{slot.lower()}"

    @property
    def native_value(self) -> str:
        contents = self.coordinator.easy_slot_contents(self._slot)
        return (contents or {}).get("name") or "none"

    @property
    def extra_state_attributes(self) -> dict | None:
        contents = self.coordinator.easy_slot_contents(self._slot)
        if not contents:
            return None
        return {"uid": contents.get("uid")}
