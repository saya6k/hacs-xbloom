"""Tools for XBloom cloud recipe sync (search/import/export/create/edit/delete).

Every tool here delegates to the matching ``coordinator.async_*_cloud_recipe``
method, which already returns a structured ``{"success": bool, "error": ...,
"message": ...}`` dict (never raises) and already checks
``cloud_login_configured`` where the wire call needs authentication — so the
"not configured" / "login failed" cases fall out of the shared
``_cloud_failure`` helper below without each tool re-checking the flag itself.
"""
from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm

from ..coordinator import POUR_PATTERN_OPTIONS
from .base import XBloomBaseTool

_LOGGER = logging.getLogger(__name__)

# Shared by create/edit — a single pour step as LLM-facing tool arguments.
_POUR_ARG_SCHEMA = vol.Schema(
    {
        vol.Required(
            "volume_ml", description="Pour volume in ml."
        ): vol.All(int, vol.Range(min=1, max=1000)),
        vol.Required(
            "temperature_c", description="Water temperature in °C."
        ): vol.All(int, vol.Range(min=0, max=100)),
        vol.Optional(
            "flow_rate",
            description="Pour flow rate, 3.0-3.5 ml/s. Defaults to 3.0.",
        ): vol.All(vol.Coerce(float), vol.Range(min=3.0, max=3.5)),
        vol.Optional(
            "pattern",
            description="Pour pattern: center, circular, or spiral. Defaults to spiral.",
        ): vol.In(list(POUR_PATTERN_OPTIONS)),
        vol.Optional(
            "pause_seconds",
            description="Seconds to pause after this pour before the next one. Defaults to 0.",
        ): vol.All(int, vol.Range(min=0, max=600)),
    }
)

# Field names shared between create (all via top-level Required/Optional) and
# edit (all Optional, partial-update). Kept in one place so the two tools'
# argument-to-recipe-dict conversion can't drift apart.
_RECIPE_SCALAR_FIELDS = (
    "name",
    "cup_type",
    "grind_size",
    "rpm",
    "dose_g",
    "ratio",
    "bypass_volume",
    "bypass_temperature",
)


def _recipe_args_to_dict(args: dict) -> dict:
    """Pull whichever recipe fields are present in tool_args into a RECIPE_SCHEMA-shaped dict."""
    recipe: dict = {}
    for key in _RECIPE_SCALAR_FIELDS:
        if key in args:
            recipe[key] = args[key]
    if "pours" in args:
        pours = []
        for p in args["pours"]:
            pour = {
                "volume_ml": int(p["volume_ml"]),
                "temperature_c": int(p["temperature_c"]),
            }
            if "flow_rate" in p:
                pour["flow_rate"] = float(p["flow_rate"])
            if "pattern" in p:
                pour["pattern"] = POUR_PATTERN_OPTIONS[p["pattern"]]
            if "pause_seconds" in p:
                pour["pause_seconds"] = int(p["pause_seconds"])
            pours.append(pour)
        recipe["pours"] = pours
    return recipe


def _cloud_failure(result: dict, action: str) -> dict:
    """Shared failure shape for every cloud tool — covers cloud_not_configured,
    login_failed, and every action-specific error the coordinator returns."""
    return {
        "success": False,
        "error": result.get("error", "unknown"),
        "instruction": (
            f"Tell the user the {action} failed: "
            f"{result.get('message', 'unknown error')}"
        ),
    }


class XBloomImportCloudRecipeTool(XBloomBaseTool):
    """Import a recipe from an XBloom cloud share URL/id as a local recipe."""

    name = "import_xbloom_cloud_recipe"
    description = (
        "Import a recipe from an XBloom cloud share URL or share id (e.g. "
        "from the official app's Share button), or from a "
        "collective.xbloom.com/recipe/{id} community-hub link, and save it "
        "as a local recipe, so it shows up in list_xbloom_recipes / "
        "execute_xbloom_recipe. No XBloom account login is required for "
        "this — both source endpoints are public."
    )
    parameters = vol.Schema(
        {
            vol.Required(
                "share_url_or_id",
                description=(
                    "A share-h5.xbloom.com URL, a "
                    "collective.xbloom.com/recipe/{id} URL, or the bare "
                    "share-h5 share id (the value after ?id= in a "
                    "share-h5.xbloom.com URL)."
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
            return _cloud_failure(result, "import")
        return {
            "success": True,
            "recipe_name": result["recipe_name"],
            "instruction": (
                f"Tell the user the recipe {result['recipe_name']!r} was "
                "imported and is now available to run via "
                "execute_xbloom_recipe."
            ),
        }


class XBloomSearchCloudRecipesTool(XBloomBaseTool):
    """List (optionally name-filtered) recipes on the configured XBloom cloud account."""

    name = "search_xbloom_cloud_recipes"
    description = (
        "List every recipe saved on the user's XBloom cloud account "
        "(visible in the official app), optionally filtered by a "
        "case-insensitive name substring. Requires an XBloom account to "
        "be configured for the machine — if not configured, this returns "
        "a cloud_not_configured error and you should tell the user to add "
        "one under Settings > Devices & Services > XBloom > Configure."
    )
    parameters = vol.Schema(
        {
            vol.Optional(
                "query",
                description=(
                    "Filter results to recipes whose name contains this "
                    "text (case-insensitive). Omit to list every recipe."
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
        query = tool_input.tool_args.get("query")
        result = await self.coordinator.async_list_cloud_recipes(query=query)
        if not result.get("success"):
            return _cloud_failure(result, "search")
        return {
            "success": True,
            "recipes": result["recipes"],
            "instruction": (
                "Read out the recipe names (and table_id if the user needs "
                "to edit/delete/export one). Mention other details only if "
                "asked."
            ),
        }


class XBloomSearchCollectiveRecipesTool(XBloomBaseTool):
    """Search XBloom's public collective.xbloom.com community recipe hub."""

    name = "search_xbloom_collective_recipes"
    description = (
        "Search XBloom's public community recipe hub (collective.xbloom.com) "
        "— recipes shared by xBloom and other users, entirely separate from "
        "the user's own private cloud account (use "
        "search_xbloom_cloud_recipes for that instead). No XBloom account "
        "is required. Results include a share_url that can be passed "
        "straight to import_xbloom_cloud_recipe to save one locally. "
        "The bean-profile filters (origin/varietal/process/roast/flavor) "
        "accept free-text names (e.g. 'Ethiopia', 'Washed', 'Dark Roast') "
        "matched case-insensitively against the hub's current filter "
        "options — any name that doesn't match is reported back under "
        "unmatched rather than silently ignored, so tell the user if that "
        "happens."
    )
    parameters = vol.Schema(
        {
            vol.Optional(
                "keyword", description="Free-text search across recipe names."
            ): str,
            vol.Optional("category", description="coffee or tea."): vol.In(
                ["coffee", "tea"]
            ),
            vol.Optional(
                "src",
                description=(
                    "official (xBloom-published) or user (community-submitted)."
                ),
            ): vol.In(["official", "user"]),
            vol.Optional(
                "machine", description="Machine model(s), e.g. Studio, Original."
            ): [str],
            vol.Optional(
                "cup_type",
                description="Cup/brewer type(s), e.g. xPod, Omni, Other, Omni Brewer.",
            ): [str],
            vol.Optional(
                "origin", description="Coffee origin(s), e.g. Ethiopia, Colombia."
            ): [str],
            vol.Optional(
                "varietal", description="Varietal(s), e.g. Bourbon, Geisha."
            ): [str],
            vol.Optional(
                "process", description="Process(es), e.g. Washed, Natural, Honey."
            ): [str],
            vol.Optional(
                "roast", description="Roast level(s), e.g. Light Roast, Dark Roast."
            ): [str],
            vol.Optional(
                "flavor", description="Flavor note(s), e.g. Blueberry, Caramel."
            ): [str],
            vol.Optional(
                "sort", description="date, likes, or downloads. Defaults to likes."
            ): vol.In(["date", "likes", "downloads"]),
            vol.Optional(
                "sort_direction", description="asc or desc. Defaults to desc."
            ): vol.In(["asc", "desc"]),
        }
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> dict:
        args = tool_input.tool_args
        result = await self.coordinator.async_search_collective_recipes(
            keyword=args.get("keyword"),
            category=args.get("category"),
            src=args.get("src"),
            machine=args.get("machine"),
            cup_type=args.get("cup_type"),
            origin=args.get("origin"),
            varietal=args.get("varietal"),
            process=args.get("process"),
            roast=args.get("roast"),
            flavor=args.get("flavor"),
            sort=args.get("sort", "likes"),
            sort_direction=args.get("sort_direction", "desc"),
        )
        if not result.get("success"):
            return _cloud_failure(result, "collective search")
        instruction = (
            "Read out the recipe names, official/user source, and likes "
            "count (and share_url if the user wants to import one via "
            "import_xbloom_cloud_recipe). Mention other details only if "
            "asked."
        )
        unmatched = result.get("unmatched")
        if unmatched:
            instruction += (
                f" These filter terms didn't match a known option and were "
                f"ignored — tell the user: {unmatched}."
            )
        return {
            "success": True,
            "recipes": result["list"],
            "total": result.get("total"),
            "instruction": instruction,
        }


class XBloomCreateCloudRecipeTool(XBloomBaseTool):
    """Create a brand-new recipe directly on the XBloom cloud account."""

    name = "create_xbloom_cloud_recipe"
    description = (
        "Create a new recipe on the user's XBloom cloud account (visible "
        "in the official app) from scratch. Use export_xbloom_recipe_to_cloud "
        "instead if the user wants to push an existing local recipe "
        "as-is. Requires an XBloom account to be configured for the "
        "machine — if not configured, this returns a cloud_not_configured "
        "error and you should tell the user to add one under Settings > "
        "Devices & Services > XBloom > Configure."
    )
    parameters = vol.Schema(
        {
            vol.Required(
                "name", description="Name for the new cloud recipe."
            ): str,
            vol.Optional(
                "cup_type",
                description=(
                    "omni_dripper for coffee, tea for tea recipes. "
                    "Defaults to omni_dripper."
                ),
            ): vol.In(["omni_dripper", "tea"]),
            vol.Optional(
                "grind_size",
                description=(
                    "Grind size 1-80 (coffee only, ignored for tea). "
                    "Defaults to 50."
                ),
            ): vol.All(int, vol.Range(min=1, max=80)),
            vol.Optional(
                "rpm",
                description=(
                    "Grinder RPM, steps of 10 from 60-120 (coffee only). "
                    "Defaults to 80."
                ),
            ): vol.All(int, vol.Range(min=60, max=120)),
            vol.Optional(
                "dose_g",
                description=(
                    "Coffee dose in grams. Use 0 for tea recipes."
                ),
            ): vol.All(vol.Coerce(float), vol.Range(min=0)),
            vol.Optional(
                "ratio",
                description=(
                    "Water ratio — total water = dose_g * ratio. Omit for "
                    "tea recipes (water is derived from the pour volumes "
                    "instead)."
                ),
            ): vol.All(vol.Coerce(float), vol.Range(min=0)),
            vol.Optional(
                "bypass_volume",
                description=(
                    "Bypass water volume in ml, 0-200 (coffee only). "
                    "Defaults to 0."
                ),
            ): vol.All(vol.Coerce(float), vol.Range(min=0, max=200)),
            vol.Optional(
                "bypass_temperature",
                description=(
                    "Bypass water temperature in °C, 0-100. Required "
                    "(non-zero) for bypass to dispense — pair with "
                    "bypass_volume."
                ),
            ): vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
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
        result = await self.coordinator.async_create_cloud_recipe(recipe)
        if not result.get("success"):
            return _cloud_failure(result, "create")
        return {
            "success": True,
            "table_id": result["table_id"],
            "share_url": result["share_url"],
            "instruction": (
                f"Tell the user the recipe {recipe['name']!r} was created "
                "on their XBloom cloud account and is now visible in the "
                "official app. Mention the share URL only if they ask to "
                "share it."
            ),
        }


class XBloomExportRecipeTool(XBloomBaseTool):
    """Push an existing local recipe to the XBloom cloud account as a new recipe."""

    name = "export_xbloom_recipe_to_cloud"
    description = (
        "Push an existing local XBloom recipe (from list_xbloom_recipes) "
        "to the user's XBloom cloud account, so it shows up in the "
        "official app and can be shared. Always creates a new cloud "
        "recipe (even if exported before). Requires an XBloom account to "
        "be configured for the machine — if not configured, this returns "
        "a cloud_not_configured error and you should tell the user to add "
        "one under Settings > Devices & Services > XBloom > Configure."
    )
    parameters = vol.Schema(
        {
            vol.Required(
                "recipe_name",
                description=(
                    "Exact name of an existing local recipe to push to "
                    "the cloud. Use list_xbloom_recipes to discover names."
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
        recipe_name = tool_input.tool_args["recipe_name"]
        result = await self.coordinator.async_export_local_recipe(recipe_name)
        if not result.get("success"):
            return _cloud_failure(result, "export")
        return {
            "success": True,
            "table_id": result["table_id"],
            "share_url": result["share_url"],
            "instruction": (
                f"Tell the user the local recipe {recipe_name!r} was "
                "pushed to their XBloom cloud account and is now visible "
                "in the official app."
            ),
        }


class XBloomEditCloudRecipeTool(XBloomBaseTool):
    """Change one or more fields of an existing cloud recipe (fetch-then-patch)."""

    name = "edit_xbloom_cloud_recipe"
    description = (
        "Change one or more fields of an existing recipe on the user's "
        "XBloom cloud account, identified by table_id (from "
        "search_xbloom_cloud_recipes or create_xbloom_cloud_recipe). Only "
        "pass the fields the user wants changed — every field you omit "
        "keeps its current value on the account. To replace a recipe's "
        "pours, pass the FULL new pour list (pours themselves are not "
        "merged field-by-field). Requires an XBloom account to be "
        "configured for the machine."
    )
    parameters = vol.Schema(
        {
            vol.Required(
                "table_id",
                description=(
                    "The cloud recipe's table ID, from "
                    "search_xbloom_cloud_recipes or create_xbloom_cloud_recipe."
                ),
            ): vol.All(int, vol.Range(min=1)),
            vol.Optional("name", description="New name for the recipe."): str,
            vol.Optional(
                "cup_type", description="omni_dripper or tea."
            ): vol.In(["omni_dripper", "tea"]),
            vol.Optional(
                "grind_size", description="New grind size, 1-80 (coffee only)."
            ): vol.All(int, vol.Range(min=1, max=80)),
            vol.Optional(
                "rpm", description="New grinder RPM, 60-120 (coffee only)."
            ): vol.All(int, vol.Range(min=60, max=120)),
            vol.Optional(
                "dose_g", description="New coffee dose in grams."
            ): vol.All(vol.Coerce(float), vol.Range(min=0)),
            vol.Optional(
                "ratio", description="New water ratio (total water = dose_g * ratio)."
            ): vol.All(vol.Coerce(float), vol.Range(min=0)),
            vol.Optional(
                "bypass_volume", description="New bypass water volume in ml, 0-200."
            ): vol.All(vol.Coerce(float), vol.Range(min=0, max=200)),
            vol.Optional(
                "bypass_temperature",
                description="New bypass water temperature in °C, 0-100.",
            ): vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
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
        table_id = int(tool_input.tool_args["table_id"])
        partial = _recipe_args_to_dict(tool_input.tool_args)
        if not partial:
            return {
                "success": False,
                "error": "no_fields",
                "instruction": (
                    "Ask the user which field(s) of the recipe they want "
                    "to change before calling edit_xbloom_cloud_recipe again."
                ),
            }
        result = await self.coordinator.async_edit_cloud_recipe(table_id, **partial)
        if not result.get("success"):
            return _cloud_failure(result, "edit")
        return {
            "success": True,
            "table_id": result["table_id"],
            "instruction": "Confirm to the user that the recipe was updated.",
        }


class XBloomDeleteCloudRecipeTool(XBloomBaseTool):
    """Permanently delete a recipe from the XBloom cloud account."""

    name = "delete_xbloom_cloud_recipe"
    description = (
        "Permanently delete a recipe from the user's XBloom cloud account, "
        "identified by table_id (from search_xbloom_cloud_recipes). This "
        "cannot be undone. SAFETY: before calling this tool with "
        "confirmed=true you MUST ask the user to confirm they want to "
        "permanently delete that specific recipe — call it once first "
        "with confirmed=false to look up the recipe's name if you don't "
        "already know it from search_xbloom_cloud_recipes."
    )
    parameters = vol.Schema(
        {
            vol.Required(
                "table_id",
                description=(
                    "The cloud recipe's table ID, from "
                    "search_xbloom_cloud_recipes."
                ),
            ): vol.All(int, vol.Range(min=1)),
            vol.Required(
                "confirmed",
                description=(
                    "Set to true ONLY after the user has explicitly "
                    "confirmed they want to permanently delete this cloud "
                    "recipe. If you have not yet asked the user, set this "
                    "to false."
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
        table_id = int(tool_input.tool_args["table_id"])
        confirmed = bool(tool_input.tool_args["confirmed"])

        if not confirmed:
            return {
                "success": False,
                "confirmation_required": True,
                "instruction": (
                    f"Do NOT delete yet. Ask the user to confirm they want "
                    f"to permanently delete cloud recipe table_id {table_id}. "
                    "Once they confirm, call delete_xbloom_cloud_recipe "
                    "again with confirmed=true."
                ),
            }

        result = await self.coordinator.async_delete_cloud_recipe(table_id)
        if not result.get("success"):
            return _cloud_failure(result, "delete")
        return {
            "success": True,
            "table_id": result["table_id"],
            "instruction": "Confirm to the user that the recipe was deleted.",
        }
