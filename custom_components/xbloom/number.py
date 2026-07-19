"""Number (slider) entities for XBloom."""
from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, UnitOfVolume
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
            XBloomGrindSizeNumber(coordinator, entry),
            XBloomRPMNumber(coordinator, entry),
            XBloomTemperatureNumber(coordinator, entry),
            XBloomVolumeNumber(coordinator, entry),
        ]
    )


class _XBloomNumber(CoordinatorEntity[XBloomCoordinator], NumberEntity):
    _attr_has_entity_name = True
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: XBloomCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)

    @property
    def device_info(self):
        return self.coordinator.device_info


class XBloomGrindSizeNumber(_XBloomNumber):
    _attr_translation_key = "grind_size"
    _attr_unique_id = "xbloom_grind_size"
    _attr_native_min_value = 1
    _attr_native_max_value = 80
    _attr_native_step = 1

    @property
    def device_info(self):
        return self.coordinator.grinder_device_info

    @property
    def native_value(self) -> float:
        return float(self.coordinator.grind_size)

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.grind_size = int(value)
        self.async_write_ha_state()
        # Live-adjust an armed grind screen (no-op otherwise) — the app
        # re-sends GRINDER_IN (8006) with the new size/RPM on the grind page.
        await self.coordinator.async_sync_armed_grinder_settings()


class XBloomRPMNumber(_XBloomNumber):
    _attr_translation_key = "rpm"
    _attr_unique_id = "xbloom_rpm"
    _attr_native_min_value = 60
    _attr_native_max_value = 120
    _attr_native_step = 10

    @property
    def device_info(self):
        return self.coordinator.grinder_device_info

    @property
    def native_value(self) -> float:
        return float(self.coordinator.rpm)

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.rpm = int(value)
        self.async_write_ha_state()
        # Live-adjust an armed grind screen (no-op otherwise) — see
        # XBloomGrindSizeNumber.
        await self.coordinator.async_sync_armed_grinder_settings()


class XBloomTemperatureNumber(_XBloomNumber):
    """Manual-pour temperature setpoint.

    Tracks the physical pour-temperature knob in real time: any RD_
    BREWER_TEMPERATURE (8108) notification — fired on a knob turn — is
    mirrored onto this value by coordinator._async_update_data. Dragging
    the slider in HA overrides it until the next knob turn.
    """

    _attr_translation_key = "temperature"
    _attr_unique_id = "xbloom_temperature"
    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_min_value = 40
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    @property
    def device_info(self):
        return self.coordinator.brewer_device_info

    @property
    def native_value(self) -> float:
        return float(self.coordinator.temperature)

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.temperature = int(value)
        self.async_write_ha_state()
        # Live-adjust an armed pour screen (no-op otherwise) — the app
        # sends BREWER_SET_TEMPERATURE (4510) live from the pour page.
        await self.coordinator.async_sync_armed_brewer_temperature()


class XBloomVolumeNumber(_XBloomNumber):
    _attr_translation_key = "volume"
    _attr_unique_id = "xbloom_volume"
    _attr_device_class = NumberDeviceClass.VOLUME
    _attr_native_min_value = 30
    _attr_native_max_value = 500
    _attr_native_step = 10
    _attr_native_unit_of_measurement = UnitOfVolume.MILLILITERS

    @property
    def device_info(self):
        return self.coordinator.brewer_device_info

    @property
    def native_value(self) -> float:
        return float(self.coordinator.volume)

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.volume = int(value)
        self.async_write_ha_state()
