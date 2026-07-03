"""Tool: write_xbloom_easy_slot — push a recipe to onboard slot A/B/C."""
from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm

from .base import XBloomBaseTool
from .recipe import _summarize_recipe

_LOGGER = logging.getLogger(__name__)

VALID_SLOTS = ("A", "B", "C")


class XBloomWriteEasySlotTool(XBloomBaseTool):
    """Write a configured recipe to one of the machine's three Easy Mode slots.

    Easy Mode slots are the A / B / C shortcuts on the device's physical
    UI. Once a recipe is pushed to a slot, the user can run that recipe
    from the machine without opening Home Assistant or the app.
    """

    name = "write_xbloom_easy_slot"
    description = (
        "Save an XBloom recipe into one of the machine's three onboard "
        "Easy Mode slots (A, B, or C). After this the user can run the "
        "recipe directly from the device's slot button without using "
        "Home Assistant. This action does NOT brew anything — it only "
        "stores the recipe on the machine. Existing slot contents are "
        "overwritten. A share URL that isn't a local recipe yet is "
        "imported first (it also lands in list_xbloom_recipes)."
    )
    parameters = vol.Schema(
        {
            vol.Required(
                "slot",
                description="Target slot — must be A, B, or C (case-insensitive).",
            ): vol.All(str, vol.Upper, vol.In(VALID_SLOTS)),
            vol.Required(
                "recipe",
                description=(
                    "Which recipe to store — its local uid, cloud table "
                    "id, share URL/id, or exact name (from "
                    "list_xbloom_recipes)."
                ),
            ): str,
        }
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> dict:
        slot_letter = str(tool_input.tool_args["slot"]).strip().upper()
        identifier = tool_input.tool_args["recipe"]

        if slot_letter not in VALID_SLOTS:
            return {
                "success": False,
                "error": "invalid_slot",
                "instruction": (
                    "Tell the user the slot must be A, B, or C and ask "
                    "which one they meant."
                ),
            }

        client = self.coordinator.client
        if client is None or not client.is_connected:
            try:
                ok = await self.coordinator.async_connect()
            except Exception as exc:
                _LOGGER.exception("auto-connect before slot write failed: %s", exc)
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

        result = await self.coordinator.async_write_easy_slot(
            slot_letter, identifier=identifier
        )
        if not result.get("success"):
            return {
                "success": False,
                "error": result.get("error", "write_failed"),
                "available_recipes": list((self.coordinator.recipes or {}).keys()),
                "instruction": (
                    "Tell the user the slot write failed: "
                    f"{result.get('message', 'unknown error')}"
                ),
            }

        recipe = (self.coordinator.recipes or {}).get(result["name"]) or {}
        return {
            "success": True,
            "slot": slot_letter,
            "recipe": _summarize_recipe(recipe),
            "instruction": (
                f"Confirm to the user that the recipe is now stored on "
                f"slot {slot_letter}, and remind them they can run it from "
                f"the machine's onboard Easy Mode buttons."
            ),
        }
