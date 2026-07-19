"""Sensor entities for XBloom."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    EntityCategory,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfElectricPotential, UnitOfTemperature, UnitOfMass
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
            XBloomFlowRateSensor(coordinator, entry),
            XBloomSerialNumberSensor(coordinator, entry),
            *(XBloomEasySlotSensor(coordinator, entry, slot) for slot in ("A", "B", "C")),
            XBloomLiveGrindSizeSensor(coordinator, entry),
            XBloomLiveGrindSpeedSensor(coordinator, entry),
            XBloomVoltageSensor(coordinator, entry),
            XBloomPourRadiusSensor(coordinator, entry),
            XBloomVibrationAmplitudeSensor(coordinator, entry),
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
    _attr_options = [
        "unknown", "idle", "grinding", "brewing", "paused", "error", "sleeping",
        "no_beans", "water_shortage", "ready", "starting", "calibrating_grinder",
        "standalone_grind", "standalone_pour", "standalone_scale", "armed_recipe",
        "awaiting_confirm", "recipe_loaded",
    ]

    @property
    def native_value(self) -> str:
        return self.coordinator.data.get("state", "unknown")


class XBloomWeightSensor(_XBloomSensor):
    _attr_translation_key = "weight"
    _attr_unique_id = "xbloom_weight"
    _attr_device_class = SensorDeviceClass.WEIGHT
    _attr_native_unit_of_measurement = UnitOfMass.GRAMS

    @property
    def device_info(self):
        return self.coordinator.scale_device_info

    @property
    def native_value(self) -> float:
        return self.coordinator.data.get("weight", 0.0)


class XBloomBrewerTempSensor(_XBloomSensor):
    _attr_translation_key = "brewer_temperature"
    _attr_unique_id = "xbloom_brewer_temp"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    @property
    def device_info(self):
        return self.coordinator.brewer_device_info

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.get("temperature")


class XBloomFlowRateSensor(_XBloomSensor):
    """Read-only — the flow rate in use right now.

    Not a control: recipes vary flow_rate per pour (see
    default_recipes.py), so a single manual setpoint doesn't represent
    "the" flow rate. During recipe execution this tracks the active
    pour's own flow_rate (updated on each RD_BLOOM/"bloom" notification —
    see coordinator._dispatch_event); otherwise it reports the manual-pour
    value (coordinator.flow_rate, settable via the pour_xbloom LLM tool).
    """

    _attr_translation_key = "flow_rate"
    _attr_unique_id = "xbloom_flow_rate"
    _attr_native_unit_of_measurement = "mL/s"

    @property
    def device_info(self):
        return self.coordinator.brewer_device_info

    @property
    def native_value(self) -> float:
        return float(self.coordinator.flow_rate)


class XBloomSerialNumberSensor(_XBloomSensor):
    _attr_translation_key = "serial_number"
    _attr_unique_id = "xbloom_serial_number"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> str:
        return self.coordinator.data.get("serial_number") or "unknown"


class XBloomLiveGrindSizeSensor(_XBloomSensor):
    """Grinder-knob position (1-80 UI units), from the physical knob or MachineInfo.

    Distinct from ``number.xbloom_grind_size`` — that's the setpoint used by
    the next standalone-grind action; this is a live read of what the
    machine itself last reported (knob turn or connect-time heartbeat).
    """

    _attr_translation_key = "live_grind_size"
    _attr_unique_id = "xbloom_live_grind_size"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def device_info(self):
        return self.coordinator.grinder_device_info

    @property
    def native_value(self) -> int | None:
        return self.coordinator.data.get("live_grind_size")


class XBloomLiveGrindSpeedSensor(_XBloomSensor):
    """Grinder RPM knob position, live from the machine (see XBloomLiveGrindSizeSensor)."""

    _attr_translation_key = "live_grind_speed"
    _attr_unique_id = "xbloom_live_grind_speed"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = "RPM"

    @property
    def device_info(self):
        return self.coordinator.grinder_device_info

    @property
    def native_value(self) -> int | None:
        return self.coordinator.data.get("live_grind_speed")


class XBloomVoltageSensor(_XBloomSensor):
    """Raw byte 39 of the RD_MachineInfo heartbeat, as volts.

    A single byte, unscaled (max 255) — fits mains voltage directly with
    no conversion needed. Live-confirmed 2026-07-04: reads 220 on a
    Korean-mains (220V) unit, a strong-enough signal to label it volts.
    """

    _attr_translation_key = "voltage_raw"
    _attr_unique_id = "xbloom_voltage_raw"
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> int | None:
        return self.coordinator.data.get("voltage")


class XBloomPourRadiusSensor(_XBloomSensor):
    """Current pour (rotation) radius — raw device value, not the 0-4 UI
    level the official app shows. Read-only; set via the
    ``advanced_settings`` service (see coordinator.async_set_advanced_settings)."""

    _attr_translation_key = "pour_radius"
    _attr_unique_id = "xbloom_pour_radius"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> int | None:
        return self.coordinator.data.get("pour_radius")


class XBloomVibrationAmplitudeSensor(_XBloomSensor):
    """Current vibration amplitude — raw device value. Read-only; set via
    the ``advanced_settings`` service."""

    _attr_translation_key = "vibration_amplitude"
    _attr_unique_id = "xbloom_vibration_amplitude"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> int | None:
        return self.coordinator.data.get("vibration_amplitude")


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
    def native_value(self) -> str | None:
        contents = self.coordinator.easy_slot_contents(self._slot)
        return (contents or {}).get("name") or None

    @property
    def extra_state_attributes(self) -> dict | None:
        contents = self.coordinator.easy_slot_contents(self._slot)
        if not contents:
            return None
        return {"uid": contents.get("uid")}
