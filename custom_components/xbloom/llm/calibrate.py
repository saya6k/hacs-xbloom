"""Tool: calibrate_xbloom_grinder — trigger the grinder gear-position
calibration sweep (cmd 3502, via coordinator.async_calibrate_grinder(),
the same call button.calibrate_grinder uses)."""
from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm

from .base import XBloomBaseTool

_LOGGER = logging.getLogger(__name__)


class XBloomCalibrateGrinderTool(XBloomBaseTool):
    """Trigger the XBloom's grinder gear-position calibration sweep."""

    name = "calibrate_xbloom_grinder"
    description = (
        "Run the XBloom's grinder gear-position calibration. Use this when "
        "the user asks to calibrate, recalibrate, or reset the grinder "
        "(e.g. after grind sizes seem off). The sweep runs autonomously on "
        "the machine for about 120 seconds after this call returns — it "
        "does not block. The action has no parameters."
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
                _LOGGER.exception(
                    "auto-connect before grinder calibration failed: %s", exc
                )
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
            await self.coordinator.async_calibrate_grinder()
        except Exception as exc:
            _LOGGER.exception("calibrate_xbloom_grinder failed: %s", exc)
            return {
                "success": False,
                "error": f"Calibration failed: {exc!s}",
            }

        return {
            "success": True,
            "instruction": (
                "Tell the user grinder calibration has started and takes "
                "about 2 minutes to finish on its own."
            ),
        }
