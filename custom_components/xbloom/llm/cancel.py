"""Tool: cancel_xbloom — cancel an armed operation or stop a running one."""
from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm

from .base import XBloomBaseTool

_LOGGER = logging.getLogger(__name__)


class XBloomCancelTool(XBloomBaseTool):
    """Back out of an armed grind/pour/recipe, or stop a running one."""

    name = "cancel_xbloom"
    description = (
        "Cancel whatever the XBloom is doing: back out of an armed "
        "(waiting-to-confirm) grind, pour, or recipe — for example when "
        "the user declines a confirmation after grind_xbloom or "
        "pour_xbloom armed the machine — or stop a grind, pour, or brew "
        "that is already running. Safe to call when nothing is active."
    )
    parameters = vol.Schema({})

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> dict:
        try:
            await self.coordinator.async_cancel()
        except Exception as exc:
            _LOGGER.exception("cancel_xbloom failed: %s", exc)
            return {"success": False, "error": f"Cancel failed: {exc!s}"}
        return {
            "success": True,
            "instruction": (
                "Briefly confirm to the user that the operation was "
                "cancelled/stopped."
            ),
        }
