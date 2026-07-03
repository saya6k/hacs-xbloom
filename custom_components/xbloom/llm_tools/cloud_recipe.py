"""Tools for XBloom cloud recipe sync (search/import/export/create/edit/delete).

Only import is implemented so far — the no-auth vertical slice from Phase 2
of the cloud recipe sync plan. The remaining cloud CRUD tools land in a
later phase alongside their coordinator methods.
"""
from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm

from .base import XBloomBaseTool

_LOGGER = logging.getLogger(__name__)


class XBloomImportCloudRecipeTool(XBloomBaseTool):
    """Import a recipe from an XBloom cloud share URL/id as a local recipe."""

    name = "import_xbloom_cloud_recipe"
    description = (
        "Import a recipe from an XBloom cloud share URL or share id (e.g. "
        "from the official app's Share button) and save it as a local "
        "recipe, so it shows up in list_xbloom_recipes / execute_xbloom_recipe. "
        "No XBloom account login is required for this — it uses XBloom's "
        "public share endpoint."
    )
    parameters = vol.Schema(
        {
            vol.Required(
                "share_url_or_id",
                description=(
                    "A share-h5.xbloom.com URL, or the bare share id "
                    "(the value after ?id= in such a URL)."
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
        share_url_or_id = tool_input.tool_args["share_url_or_id"]
        result = await self.coordinator.async_import_cloud_recipe(share_url_or_id)
        if not result.get("success"):
            return {
                "success": False,
                "error": result.get("error", "unknown"),
                "instruction": (
                    f"Tell the user the import failed: "
                    f"{result.get('message', 'unknown error')}"
                ),
            }
        return {
            "success": True,
            "recipe_name": result["recipe_name"],
            "instruction": (
                f"Tell the user the recipe {result['recipe_name']!r} was "
                "imported and is now available to run via "
                "execute_xbloom_recipe."
            ),
        }
