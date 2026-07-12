"""Tool: get_xbloom_status — read current machine state."""
from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm

from .base import XBloomBaseTool

_LOGGER = logging.getLogger(__name__)


class XBloomStatusTool(XBloomBaseTool):
    """Return the current state of the XBloom machine."""

    name = "get_xbloom_status"
    description = (
        "Get the current status of the XBloom coffee machine: BLE connection, "
        "running state (idle/grinding/brewing/paused/error/sleeping), brewer "
        "temperature, scale weight, water level, firmware version, and any "
        "active error."
    )
    parameters = vol.Schema({})

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> dict:
        client = self.coordinator.client
        if client is None or not client.is_connected:
            try:
                ok = await self.coordinator.async_connect()
            except Exception as exc:
                _LOGGER.exception("auto-connect before status failed: %s", exc)
                ok = False
            if not ok:
                return {
                    "connected": False,
                    "mac_address": self.coordinator.mac_address,
                    "error": "connect_failed",
                    "instruction": (
                        "Tell the user the XBloom could not be reached over "
                        "Bluetooth. Ask them to check the machine is powered "
                        "on and in range."
                    ),
                }

        data = self.coordinator.data or {}

        return {
            "connected": True,
            "mac_address": self.coordinator.mac_address,
            "state": data.get("state", "unknown"),
            "brewer_temperature_c": data.get("temperature", 0.0),
            "scale_weight_g": data.get("weight", 0.0),
            "grinder_running": bool(data.get("grinder_running")),
            "brewer_running": bool(data.get("brewer_running")),
            "water_level_ok": bool(data.get("water_level_ok")),
            "firmware_version": data.get("version") or "",
            "serial_number": data.get("serial_number") or "",
            "error": data.get("error"),
            "instruction": (
                "Summarize the machine status conversationally. Mention only "
                "the fields that are relevant to what the user asked. Do not "
                "list raw key/value pairs."
            ),
        }
