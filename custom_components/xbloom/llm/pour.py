"""Tool: pour_xbloom — manual pour with custom temperature and volume."""
from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm

from .base import XBloomBaseTool

_LOGGER = logging.getLogger(__name__)

# Safety limits.
# Temperature has a controlled range of 40–95°C plus a special "boiling"
# mode triggered by sending 100°C to the brewer.
TEMPERATURE_MIN_C = 40
TEMPERATURE_MAX_C = 95
TEMPERATURE_BOILING_C = 100
VOLUME_MIN_ML = 10
VOLUME_MAX_ML = 500
FLOW_RATE_MIN = 3.0
FLOW_RATE_MAX = 3.5


class XBloomPourTool(XBloomBaseTool):
    """Start a manual pour with the requested temperature and volume."""

    name = "pour_xbloom"
    description = (
        "Pour water from the XBloom with a custom temperature and volume. "
        "This is a manual pour — it does NOT grind beans. Temperature is in "
        "degrees Celsius (40–95) or set boiling=true for the boiling-point "
        "mode (used for tea or descaling). Volume is in milliliters. The "
        "pour starts immediately, so only call this when the user has asked "
        "to pour."
    )
    parameters = vol.Schema(
        {
            vol.Optional(
                "temperature",
                description=(
                    f"Water temperature in Celsius "
                    f"({TEMPERATURE_MIN_C}–{TEMPERATURE_MAX_C}). Required "
                    "unless boiling=true."
                ),
            ): vol.All(vol.Coerce(float), vol.Range(min=TEMPERATURE_MIN_C, max=TEMPERATURE_MAX_C)),
            vol.Optional(
                "boiling",
                description=(
                    "Set to true to use the boiling-point mode instead of a "
                    "specific temperature. When true, the temperature field "
                    "is ignored."
                ),
                default=False,
            ): bool,
            vol.Required(
                "volume",
                description=(
                    f"Volume of water in milliliters "
                    f"({VOLUME_MIN_ML}–{VOLUME_MAX_ML})."
                ),
            ): vol.All(vol.Coerce(int), vol.Range(min=VOLUME_MIN_ML, max=VOLUME_MAX_ML)),
            vol.Optional(
                "flow_rate",
                description=(
                    f"Flow rate in ml/s ({FLOW_RATE_MIN}–{FLOW_RATE_MAX}). "
                    "Defaults to the machine's current setting."
                ),
            ): vol.All(vol.Coerce(float), vol.Range(min=FLOW_RATE_MIN, max=FLOW_RATE_MAX)),
        }
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> dict:
        args = tool_input.tool_args
        boiling = bool(args.get("boiling", False))
        if boiling:
            temperature = float(TEMPERATURE_BOILING_C)
        elif "temperature" in args:
            temperature = float(args["temperature"])
        else:
            return {
                "success": False,
                "error": "missing_temperature",
                "instruction": (
                    "Ask the user what temperature they want, between "
                    f"{TEMPERATURE_MIN_C}°C and {TEMPERATURE_MAX_C}°C, or "
                    "whether they want boiling-point water."
                ),
            }
        volume = int(args["volume"])
        flow_rate = args.get("flow_rate")

        client = self.coordinator.client
        if client is None or not client.is_connected:
            try:
                ok = await self.coordinator.async_connect()
            except Exception as exc:
                _LOGGER.exception("auto-connect before pour failed: %s", exc)
                ok = False
            if not ok:
                return {
                    "success": False,
                    "error": "connect_failed",
                    "instruction": (
                        "Tell the user the XBloom could not be reached over "
                        "Bluetooth. Ask them to check the machine is powered "
                        "on and in range."
                    ),
                }

        # Mirror the slider state so the corresponding number entities reflect
        # what was actually requested.
        self.coordinator.temperature = int(round(temperature))
        self.coordinator.volume = volume
        if flow_rate is not None:
            self.coordinator.flow_rate = float(flow_rate)

        try:
            await self.coordinator.async_pour()
        except Exception as exc:
            _LOGGER.exception("pour_xbloom failed: %s", exc)
            return {
                "success": False,
                "error": f"Pour failed: {exc!s}",
            }

        # Notify entities that slider state changed.
        self.coordinator.async_update_listeners()

        return {
            "success": True,
            "temperature_c": temperature,
            "boiling": boiling,
            "volume_ml": volume,
            "flow_rate_ml_s": self.coordinator.flow_rate,
            "instruction": (
                "Briefly confirm to the user that the pour has started. If "
                "boiling=true, describe it as 'boiling water'; otherwise "
                "mention the temperature in Celsius."
            ),
        }
