"""Tool: grind_xbloom — manual grind with custom size and RPM."""
from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm

from .base import XBloomBaseTool

_LOGGER = logging.getLogger(__name__)

# Mirrors number.py's XBloomGrindSizeNumber/XBloomRPMNumber bounds.
GRIND_SIZE_MIN = 1
GRIND_SIZE_MAX = 80
RPM_MIN = 60
RPM_MAX = 120


class XBloomGrindTool(XBloomBaseTool):
    """Start a manual grind with the requested grind size and RPM."""

    name = "grind_xbloom"
    description = (
        "Grind beans on the XBloom with a custom grind size and RPM. This "
        "is a manual grind — it does NOT pour water. Two-phase flow: the "
        "first call (without confirmed) ARMS the machine — it opens its "
        "grind page showing the requested settings without starting — and "
        "you must then ask the user to confirm. Call again with "
        "confirmed=true to start the grind; if the user declines, call "
        "cancel_xbloom to back out. Use pour_xbloom afterwards for a "
        "manual pour, or execute_xbloom_recipe to grind and pour a full "
        "recipe in one call."
    )
    parameters = vol.Schema(
        {
            vol.Optional(
                "grind_size",
                description=(
                    f"Grind size on the XBloom Studio scale "
                    f"({GRIND_SIZE_MIN}=finest–{GRIND_SIZE_MAX}=coarsest). "
                    "Defaults to the machine's current setting — see "
                    "execute_xbloom_recipe's GRIND SIZE REFERENCE for "
                    "recommended ranges per brew method."
                ),
            ): vol.All(vol.Coerce(int), vol.Range(min=GRIND_SIZE_MIN, max=GRIND_SIZE_MAX)),
            vol.Optional(
                "rpm",
                description=(
                    f"Grinder speed in RPM ({RPM_MIN}–{RPM_MAX}). Defaults "
                    "to the machine's current setting."
                ),
            ): vol.All(vol.Coerce(int), vol.Range(min=RPM_MIN, max=RPM_MAX)),
            vol.Optional(
                "confirmed",
                default=False,
                description=(
                    "Set to true ONLY after the user has confirmed starting "
                    "the grind the first (arming) call announced."
                ),
            ): bool,
        }
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> dict:
        args = tool_input.tool_args
        grind_size = args.get("grind_size")
        rpm = args.get("rpm")

        client = self.coordinator.client
        if client is None or not client.is_connected:
            try:
                ok = await self.coordinator.async_connect()
            except Exception as exc:
                _LOGGER.exception("auto-connect before grind failed: %s", exc)
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

        # Mirror the slider state so the corresponding number entities
        # reflect what was actually requested.
        if grind_size is not None:
            self.coordinator.grind_size = int(grind_size)
        if rpm is not None:
            self.coordinator.rpm = int(rpm)

        confirmed = bool(args.get("confirmed", False))
        try:
            if not confirmed:
                # Phase 1: arm — the machine opens its grind page showing
                # the requested settings while the user is being asked.
                await self.coordinator.async_arm_grind()
            elif self.coordinator._armed_operation == "grind":
                # Phase 2: the arm is still standing — bare start.
                await self.coordinator.async_confirm_grind()
            else:
                # confirmed=true without a live arm (fresh conversation,
                # or the arm was cleared machine-side) — one-shot start.
                await self.coordinator.async_grind()
        except Exception as exc:
            _LOGGER.exception("grind_xbloom failed: %s", exc)
            return {
                "success": False,
                "error": f"Grind failed: {exc!s}",
            }

        # Notify entities that slider state changed.
        self.coordinator.async_update_listeners()

        if not confirmed:
            return {
                "success": True,
                "armed": True,
                "grind_size": self.coordinator.grind_size,
                "rpm": self.coordinator.rpm,
                "instruction": (
                    "The machine is now showing its grind page with these "
                    "settings. Ask the user to confirm starting the grind; "
                    "if they agree, call grind_xbloom again with "
                    "confirmed=true. If they decline, call cancel_xbloom."
                ),
            }
        return {
            "success": True,
            "grind_size": self.coordinator.grind_size,
            "rpm": self.coordinator.rpm,
            "instruction": "Briefly confirm to the user that grinding has started.",
        }
