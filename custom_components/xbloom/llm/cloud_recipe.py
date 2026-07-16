"""Tools for the XBloom cloud boundary (import / export / collective search).

The local recipe store is the source of truth — these tools only cross the
network edge: import clones a shared recipe into the store, export pushes a
local recipe to the user's cloud account, and the collective search browses
the public hub. Each delegates to the matching coordinator method, which
returns a structured ``{"success": bool, "error": ..., "message": ...}`` dict
(never raises) and already checks ``cloud_login_configured`` where the wire
call needs authentication — so the "not configured" / "login failed" cases
fall out of the shared ``_cloud_failure`` helper below.
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
            "uid": result["uid"],
            "recipe_name": result["name"],
            "instruction": (
                f"Tell the user the recipe {result['name']!r} was "
                "imported and is now available to run via "
                "execute_xbloom_recipe."
            ),
        }


class XBloomSearchCollectiveRecipesTool(XBloomBaseTool):
    """Search XBloom's public collective.xbloom.com community recipe hub."""

    name = "search_xbloom_collective_recipes"
    description = (
        "Search XBloom's public community recipe hub (collective.xbloom.com) "
        "— recipes shared by xBloom and other users, entirely separate from "
        "the user's local recipes (use list_xbloom_recipes for those). No "
        "XBloom account is required. Results include a share_url that can be passed "
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


class XBloomExportRecipeTool(XBloomBaseTool):
    """Export a local recipe to the XBloom cloud account (share link)."""

    name = "export_xbloom_recipe"
    description = (
        "Export a local XBloom recipe to the user's XBloom cloud account "
        "so it shows up in the official app and gets a share link. If the "
        "recipe was exported before, the same cloud recipe is updated in "
        "place (its id and share link stay stable). Without a configured "
        "XBloom account nothing is uploaded — the tool returns just the "
        "recipe definition, with no cloud id or share link."
    )
    parameters = vol.Schema(
        {
            vol.Required(
                "recipe",
                description=(
                    "Which recipe to export — its local uid, cloud table "
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
        identifier = tool_input.tool_args["recipe"]
        result = await self.coordinator.async_export_recipe(identifier)
        if not result.get("success"):
            return _cloud_failure(result, "export")
        out: dict = {"success": True, "recipe": result["recipe"]}
        if "id" in result:
            out["id"] = result["id"]
            out["link"] = result.get("link")
            out["instruction"] = (
                "Tell the user the recipe is now on their XBloom cloud "
                "account (visible in the official app), and read out the "
                "share link if they asked to share it."
            )
        else:
            out["instruction"] = (
                "No XBloom cloud account is configured, so nothing was "
                "uploaded — the recipe stays local only. Tell the user "
                "they can add an account under Settings > Devices & "
                "Services > XBloom > Configure to get a share link."
            )
        if result.get("warning"):
            out["warning"] = result["warning"]
            out["instruction"] += " Also mention this warning: " + result["warning"]
        return out
