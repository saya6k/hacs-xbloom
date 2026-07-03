"""Tools for local recipe store CRUD: create / edit / delete.

The local store is the source of truth (what the Recipe dropdown shows).
These tools never touch the cloud — publishing a local recipe is
``export_xbloom_recipe``; pulling a shared one in is
``import_xbloom_cloud_recipe``. Each delegates to the coordinator's
local-store methods, sharing the pour/scalar argument schemas with the
cloud tools so the two surfaces can't drift apart.
"""
from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm

from .base import XBloomBaseTool
from .cloud_recipe import _POUR_ARG_SCHEMA, _cloud_failure, _recipe_args_to_dict
from .recipe import _RECIPE_ID_DESCRIPTION

_LOGGER = logging.getLogger(__name__)

_RECIPE_SCALAR_ARGS = {
    vol.Optional(
        "cup_type",
        description=(
            "omni_dripper for coffee, tea for tea recipes. Defaults to "
            "omni_dripper."
        ),
    ): vol.In(["omni_dripper", "tea"]),
    vol.Optional(
        "grind_size",
        description="Grind size 1-80 (coffee only, ignored for tea). Defaults to 50.",
    ): vol.All(int, vol.Range(min=1, max=80)),
    vol.Optional(
        "rpm",
        description="Grinder RPM, steps of 10 from 60-120 (coffee only). Defaults to 80.",
    ): vol.All(int, vol.Range(min=60, max=120)),
    vol.Optional(
        "dose_g",
        description="Coffee dose in grams. Use 0 for tea recipes.",
    ): vol.All(vol.Coerce(float), vol.Range(min=0)),
    vol.Optional(
        "ratio",
        description=(
            "Water ratio — total water = dose_g * ratio. Omit for tea "
            "recipes (water is derived from the pour volumes instead)."
        ),
    ): vol.All(vol.Coerce(float), vol.Range(min=0)),
    vol.Optional(
        "bypass_volume",
        description="Bypass water volume in ml, 0-200 (coffee only). Defaults to 0.",
    ): vol.All(vol.Coerce(float), vol.Range(min=0, max=200)),
    vol.Optional(
        "bypass_temperature",
        description=(
            "Bypass water temperature in °C, 0-100. Required (non-zero) "
            "for bypass to dispense — pair with bypass_volume."
        ),
    ): vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
}


class XBloomCreateRecipeTool(XBloomBaseTool):
    """Create a new local recipe from scratch."""

    name = "create_xbloom_recipe"
    description = (
        "Create a new local XBloom recipe from scratch. It appears in the "
        "Recipe dropdown immediately and gets a local uid (returned). "
        "Nothing is uploaded — use export_xbloom_recipe afterwards if the "
        "user wants it on their XBloom cloud account / a share link."
    )
    parameters = vol.Schema(
        {
            vol.Required("name", description="Name for the new recipe."): str,
            **_RECIPE_SCALAR_ARGS,
            vol.Required(
                "pours",
                description="One or more pour steps, in order.",
            ): [_POUR_ARG_SCHEMA],
        }
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> dict:
        recipe = _recipe_args_to_dict(tool_input.tool_args)
        result = self.coordinator.create_local_recipe(recipe)
        if not result.get("success"):
            return _cloud_failure(result, "create")
        return {
            "success": True,
            "uid": result["uid"],
            "recipe_name": result["name"],
            "instruction": (
                f"Tell the user the recipe {result['name']!r} was created "
                "and is available in the Recipe dropdown and via "
                "execute_xbloom_recipe."
            ),
        }


class XBloomEditRecipeTool(XBloomBaseTool):
    """Change one or more fields of a local recipe."""

    name = "edit_xbloom_recipe"
    description = (
        "Change one or more fields of a local XBloom recipe. Only pass the "
        "fields the user wants changed — every omitted field keeps its "
        "current value. To replace the pours, pass the FULL new pour list. "
        "Cloud recipes are never edited directly: pointing this at a share "
        "URL that isn't local yet imports a local copy first and edits "
        "that."
    )
    parameters = vol.Schema(
        {
            vol.Required("recipe", description=_RECIPE_ID_DESCRIPTION): str,
            vol.Optional("name", description="New name for the recipe."): str,
            **_RECIPE_SCALAR_ARGS,
            vol.Optional(
                "pours",
                description="Full replacement list of pour steps, in order.",
            ): [_POUR_ARG_SCHEMA],
        }
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> dict:
        identifier = tool_input.tool_args["recipe"]
        changes = _recipe_args_to_dict(tool_input.tool_args)
        if not changes:
            return {
                "success": False,
                "error": "no_fields",
                "instruction": (
                    "Ask the user which field(s) of the recipe they want "
                    "to change before calling edit_xbloom_recipe again."
                ),
            }
        result = await self.coordinator.async_edit_local_recipe(identifier, changes)
        if not result.get("success"):
            return _cloud_failure(result, "edit")
        return {
            "success": True,
            "uid": result["uid"],
            "recipe_name": result["name"],
            "instruction": "Confirm to the user that the recipe was updated.",
        }


class XBloomDeleteRecipeTool(XBloomBaseTool):
    """Delete a local recipe (cloud copies are untouched)."""

    name = "delete_xbloom_recipe"
    description = (
        "Delete a local XBloom recipe — it disappears from the Recipe "
        "dropdown immediately. A copy on the user's XBloom cloud account "
        "(if any) is NOT touched; cloud copies are managed from the "
        "official app. SAFETY: before calling this tool with "
        "confirmed=true you MUST ask the user to confirm they want to "
        "delete that specific recipe."
    )
    parameters = vol.Schema(
        {
            vol.Required("recipe", description=_RECIPE_ID_DESCRIPTION): str,
            vol.Required(
                "confirmed",
                description=(
                    "Set to true ONLY after the user has explicitly "
                    "confirmed they want to delete this recipe. If you "
                    "have not yet asked the user, set this to false."
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
        identifier = tool_input.tool_args["recipe"]
        if not bool(tool_input.tool_args["confirmed"]):
            return {
                "success": False,
                "confirmation_required": True,
                "instruction": (
                    f"Do NOT delete yet. Ask the user to confirm they want "
                    f"to delete the recipe {identifier!r}. Once they "
                    "confirm, call delete_xbloom_recipe again with "
                    "confirmed=true."
                ),
            }
        result = self.coordinator.delete_local_recipe(identifier)
        if not result.get("success"):
            return _cloud_failure(result, "delete")
        return {
            "success": True,
            "uid": result["uid"],
            "recipe_name": result["name"],
            "instruction": (
                "Confirm to the user that the local recipe was deleted. If "
                "it also exists on their XBloom cloud account, mention that "
                "copy is untouched."
            ),
        }
