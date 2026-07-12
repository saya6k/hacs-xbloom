"""Tool: tare_xbloom_scale — zero the scale (cmd 8500)."""
from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm

from .base import XBloomBaseTool

_LOGGER = logging.getLogger(__name__)


class XBloomTareScaleTool(XBloomBaseTool):
    """Zero the XBloom scale."""

    name = "tare_xbloom_scale"
    description = (
        "Zero (tare) the XBloom built-in scale. Use this when the user asks "
        "to tare, zero, or reset the scale, or after they've placed a cup or "
        "dripper and want the reading to start at 0 g. The action is instant "
        "and has no parameters."
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
                _LOGGER.exception("auto-connect before tare failed: %s", exc)
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

        try:
            await self.coordinator.async_tare_scale()
        except Exception as exc:
            _LOGGER.exception("tare_xbloom_scale failed: %s", exc)
            return {
                "success": False,
                "error": f"Tare failed: {exc!s}",
            }

        return {
            "success": True,
            "instruction": "Briefly confirm to the user that the scale has been zeroed.",
        }
