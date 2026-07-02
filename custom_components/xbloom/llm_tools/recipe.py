"""Tools: list_xbloom_recipes and execute_xbloom_recipe."""
from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm

from ..coordinator import POUR_PATTERN_OPTIONS, WATER_SOURCE_TANK
from .base import XBloomBaseTool

_LOGGER = logging.getLogger(__name__)

# Minimum scale weight (g) used to detect that a cup/dripper is sitting on
# the platform. Tare drift typically stays under 5 g; a real cup or dripper
# sits well above this floor.
CUP_PRESENCE_WEIGHT_G = 20.0

# int → name, for surfacing pour patterns to the LLM in get_xbloom_recipe.
_PATTERN_INT_TO_NAME = {v: k for k, v in POUR_PATTERN_OPTIONS.items()}


def _summarize_recipe(raw: dict) -> dict:
    """Pull the user-facing fields out of a raw YAML recipe dict."""
    pours = raw.get("pours") or []
    return {
        "name": raw.get("name"),
        "cup_type": raw.get("cup_type", "omni_dripper"),
        "bean_weight_g": raw.get("bean_weight"),
        "grind_size": raw.get("grind_size"),
        "total_water_ml": raw.get("total_water"),
        "pour_count": len(pours),
    }


def _detail_recipe(raw: dict) -> dict:
    """Full recipe detail, including every pour, for the get tool.

    Pour patterns are surfaced as names (center/circular/spiral) but the
    pour_index in execute_xbloom_recipe's pour_overrides is 0-based to
    match the order returned here.
    """
    pours = []
    for i, p in enumerate(raw.get("pours") or []):
        pat = p.get("pattern", 2)
        if isinstance(pat, str):
            pat_name = pat.strip().lower()
        else:
            pat_name = _PATTERN_INT_TO_NAME.get(int(pat), "spiral")
        pours.append({
            "pour_index": i,
            "volume_ml": p.get("volume"),
            "temperature_c": p.get("temperature"),
            "flow_rate": p.get("flow_rate", 3.0),
            "pattern": pat_name,
            "pausing_s": p.get("pausing", 0),
        })
    return {
        "name": raw.get("name"),
        "cup_type": raw.get("cup_type", "omni_dripper"),
        "grind_size": raw.get("grind_size"),
        "rpm": raw.get("rpm"),
        "bean_weight_g": raw.get("bean_weight"),
        "total_water_ml": raw.get("total_water"),
        "bypass_volume_ml": raw.get("bypass_volume", 0),
        "bypass_temperature_c": raw.get("bypass_temperature", 0),
        "pours": pours,
    }


class XBloomGetRecipeTool(XBloomBaseTool):
    """Return the full configuration of one saved recipe."""

    name = "get_xbloom_recipe"
    description = (
        "Get the full configuration of one saved XBloom recipe by name: "
        "grind size, RPM, bean weight, total water, and every pour's "
        "volume, temperature, flow rate, and pour pattern (with 0-based "
        "pour_index). Use this before execute_xbloom_recipe when the user "
        "wants to tweak the grind, RPM, or any individual pour's volume / "
        "flow rate / pattern, so you know the current values and which "
        "pour_index to target."
    )
    parameters = vol.Schema(
        {
            vol.Required(
                "recipe_name",
                description="The exact name of the configured recipe.",
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
        recipes = self.coordinator.recipes or {}
        if recipe_name not in recipes:
            return {
                "success": False,
                "error": "recipe_not_found",
                "available_recipes": list(recipes.keys()),
                "instruction": (
                    "Tell the user that recipe was not found and list the "
                    "available recipes so they can pick one."
                ),
            }
        return {
            "success": True,
            "recipe": _detail_recipe(recipes[recipe_name]),
            "instruction": (
                "Use these values to decide any grind_size / rpm / "
                "pour_overrides you pass to execute_xbloom_recipe. Only "
                "override what the user asked to change."
            ),
        }


class XBloomListRecipesTool(XBloomBaseTool):
    """List recipes configured for this machine."""

    name = "list_xbloom_recipes"
    description = (
        "List the names of recipes configured for the XBloom in "
        "configuration.yaml, along with a short summary of each "
        "(cup type, bean weight, total water, number of pours)."
    )
    parameters = vol.Schema({})

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> dict:
        recipes = self.coordinator.recipes or {}
        if not recipes:
            return {
                "recipes": [],
                "instruction": (
                    "Tell the user no recipes are configured and they can add "
                    "some under the xbloom section in configuration.yaml."
                ),
            }
        return {
            "recipes": [_summarize_recipe(r) for r in recipes.values()],
            "instruction": (
                "Read out the recipe names. Mention details only if the user "
                "asks for them."
            ),
        }


class XBloomExecuteRecipeTool(XBloomBaseTool):
    """Execute a saved recipe by name, after the user confirms beans are loaded."""

    name = "execute_xbloom_recipe"
    description = (
        "Execute a saved XBloom recipe by name. SAFETY: before calling this "
        "tool you MUST ask the user to confirm: (1) that beans (or tea "
        "leaves, for tea recipes) have been added, (2) that the paper "
        "coffee filter has been installed (the machine cannot detect the "
        "filter on its own), and (3) that the cup or dripper is on the "
        "scale. The tool can usually detect the cup automatically by its "
        "weight; however, if a cup was placed before the machine powered "
        "on, the scale reads it as 0 g — in that case the tool will ask "
        "the user to verify the cup and you should pass cup_confirmed=true "
        "after the user confirms. Water level is checked automatically "
        "(no user confirmation needed) — the tool refuses to start and "
        "returns error='water_low' if the tank needs a refill. This check "
        "is skipped when the Water Source select is set to 'direct' (hose "
        "feed), since the low-water sensor only tracks the internal tank."
    )
    parameters = vol.Schema(
        {
            vol.Required(
                "recipe_name",
                description="The exact name of the configured recipe to run.",
            ): str,
            vol.Required(
                "beans_confirmed",
                description=(
                    "Set to true ONLY after the user has explicitly confirmed "
                    "that beans (or tea leaves) have been loaded. If you have "
                    "not yet asked the user, set this to false."
                ),
            ): bool,
            vol.Required(
                "filter_confirmed",
                description=(
                    "Set to true ONLY after the user has explicitly confirmed "
                    "that the paper coffee filter is installed. The machine "
                    "cannot detect this on its own, so you must ask the user. "
                    "For tea recipes the filter is not needed and you may "
                    "still pass true once the user has confirmed they are "
                    "ready."
                ),
            ): bool,
            vol.Required(
                "cup_confirmed",
                description=(
                    "Set to true ONLY after the user has explicitly confirmed "
                    "that the cup or dripper is on the scale. If the scale "
                    "already shows weight from the cup, the tool will accept "
                    "the call without asking, even if you pass false. You "
                    "only need to pass true when the previous call returned "
                    "cup_unverified, meaning the scale was tared at 0 g with "
                    "the cup on it (this happens when the cup was placed "
                    "before the machine powered on)."
                ),
            ): bool,
            vol.Optional(
                "grind_size",
                description=(
                    "Optional grind-size override (1-80) for this brew only. "
                    "Coffee recipes only; ignored for tea / no-grind recipes. "
                    "Omit to use the recipe's saved grind size."
                ),
            ): vol.All(int, vol.Range(min=1, max=80)),
            vol.Optional(
                "rpm",
                description=(
                    "Optional grinder RPM override for this brew only, in "
                    "steps of 10 from 60 to 120. Coffee recipes only. Omit "
                    "to use the recipe's saved RPM."
                ),
            ): vol.All(int, vol.Range(min=60, max=120)),
            vol.Optional(
                "bypass_volume",
                description=(
                    "Optional bypass water volume in ml (0-200) for this brew "
                    "only. Bypass dilutes the brew with extra water after the "
                    "pours. Coffee recipes only; ignored for tea. Set to 0 to "
                    "disable bypass. Can be added even if the recipe has none."
                ),
            ): vol.All(int, vol.Range(min=0, max=200)),
            vol.Optional(
                "bypass_temperature",
                description=(
                    "Optional bypass water temperature in °C (0-100) for this "
                    "brew only. Coffee recipes only. Required (non-zero) for "
                    "bypass to dispense — pair it with bypass_volume."
                ),
            ): vol.All(int, vol.Range(min=0, max=100)),
            vol.Optional(
                "pour_overrides",
                description=(
                    "Optional per-pour tweaks for this brew only. A list of "
                    "objects, each with a 0-based pour_index (from "
                    "get_xbloom_recipe) and any of: volume (30-500 ml), "
                    "flow_rate (3.0-3.5 ml/s), pattern (center/circular/"
                    "spiral). Only include the pours and fields you want to "
                    "change."
                ),
            ): [
                vol.Schema(
                    {
                        vol.Required("pour_index"): vol.All(int, vol.Range(min=0)),
                        vol.Optional("volume"): vol.All(int, vol.Range(min=30, max=500)),
                        vol.Optional("flow_rate"): vol.All(
                            vol.Coerce(float), vol.Range(min=3.0, max=3.5)
                        ),
                        vol.Optional("pattern"): vol.In(list(POUR_PATTERN_OPTIONS)),
                    }
                )
            ],
        }
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> dict:
        recipe_name = tool_input.tool_args["recipe_name"]
        beans_confirmed = bool(tool_input.tool_args["beans_confirmed"])
        filter_confirmed = bool(tool_input.tool_args["filter_confirmed"])
        cup_confirmed = bool(tool_input.tool_args["cup_confirmed"])

        recipes = self.coordinator.recipes or {}
        if recipe_name not in recipes:
            available = list(recipes.keys())
            return {
                "success": False,
                "error": "recipe_not_found",
                "available_recipes": available,
                "instruction": (
                    "Tell the user that recipe was not found. If there are "
                    "available recipes, mention them so the user can pick one."
                ),
            }

        recipe = recipes[recipe_name]
        cup_type = (recipe.get("cup_type") or "omni_dripper").lower()
        is_tea = cup_type == "tea"
        ingredient = "tea leaves" if is_tea else "beans"

        missing: list[str] = []
        if not beans_confirmed:
            missing.append(ingredient)
        if not filter_confirmed and not is_tea:
            missing.append("paper coffee filter")

        if missing:
            items = " and ".join(missing)
            return {
                "success": False,
                "confirmation_required": True,
                "missing_confirmations": missing,
                "recipe": _summarize_recipe(recipe),
                "instruction": (
                    f"Do NOT start the recipe yet. Ask the user to confirm "
                    f"that the {items} have been added/installed for the "
                    f"'{recipe_name}' recipe. The machine cannot detect the "
                    f"filter on its own, so the user must verify it manually. "
                    f"Once they confirm, call execute_xbloom_recipe again "
                    f"with beans_confirmed=true and filter_confirmed=true."
                ),
            }

        client = self.coordinator.client
        if client is None or not client.is_connected:
            try:
                ok = await self.coordinator.async_connect()
            except Exception as exc:
                _LOGGER.exception("auto-connect before recipe failed: %s", exc)
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

        # Water level: machine-reported, no user confirmation needed — but
        # check it before cup/select/execute so a low-water machine is
        # caught up front instead of failing partway through the brew
        # sequence. See coordinator.async_execute_recipe for the low-level
        # guard; this is the LLM-facing early check. Skipped on a direct
        # (hose) feed — water_level_ok tracks the internal tank sensor,
        # which a hose setup doesn't rely on.
        if self.coordinator.water_source == WATER_SOURCE_TANK and not (
            self.coordinator.data or {}
        ).get("water_level_ok", True):
            return {
                "success": False,
                "error": "water_low",
                "instruction": (
                    "Do NOT start the recipe. Tell the user the XBloom's "
                    "water tank is low and ask them to refill it before "
                    "brewing. Do not retry until they confirm it's refilled."
                ),
            }

        # Cup presence: weight > threshold proves a cup is there. A reading
        # near 0 g is ambiguous because the machine auto-tares any weight
        # present at power-on, so a cup placed before boot reads as 0 g.
        # When ambiguous, fall back to a manual user confirmation.
        weight = float((self.coordinator.data or {}).get("weight", 0.0) or 0.0)
        cup_on_scale = weight >= CUP_PRESENCE_WEIGHT_G
        if not cup_on_scale and not cup_confirmed:
            return {
                "success": False,
                "error": "cup_unverified",
                "scale_weight_g": weight,
                "instruction": (
                    "Do NOT start the recipe yet. The scale reads "
                    f"{weight:.1f} g, which means either no cup is on the "
                    "machine OR a cup was placed before power-on (the "
                    "machine tares any weight at boot to 0 g). Ask the "
                    "user to confirm the cup or dripper is on the scale. "
                    "Once they confirm, call execute_xbloom_recipe again "
                    "with cup_confirmed=true."
                ),
            }

        # Select the recipe (also syncs the grind/RPM sliders to it for
        # coffee grinding recipes), then layer any explicit overrides on top.
        self.coordinator.select_recipe(recipe_name)

        args = tool_input.tool_args
        bypass_volume = None
        bypass_temperature = None
        if not is_tea:
            if "grind_size" in args:
                self.coordinator.grind_size = int(args["grind_size"])
            if "rpm" in args:
                self.coordinator.rpm = int(args["rpm"])
            if "bypass_volume" in args:
                bypass_volume = float(args["bypass_volume"])
            if "bypass_temperature" in args:
                bypass_temperature = float(args["bypass_temperature"])

        pour_overrides = []
        for ov in args.get("pour_overrides") or []:
            entry = {"pour_index": int(ov["pour_index"])}
            if "volume" in ov:
                entry["volume"] = int(ov["volume"])
            if "flow_rate" in ov:
                entry["flow_rate"] = float(ov["flow_rate"])
            if "pattern" in ov:
                entry["pattern"] = POUR_PATTERN_OPTIONS[ov["pattern"]]
            pour_overrides.append(entry)

        try:
            await self.coordinator.async_execute_recipe(
                pour_overrides=pour_overrides or None,
                bypass_volume=bypass_volume,
                bypass_temperature=bypass_temperature,
            )
        except Exception as exc:
            _LOGGER.exception("execute_xbloom_recipe failed: %s", exc)
            return {
                "success": False,
                "error": f"Execution failed: {exc!s}",
            }

        # Reflect the selection on the select entity.
        self.coordinator.async_update_listeners()

        return {
            "success": True,
            "recipe": _summarize_recipe(recipe),
            "instruction": (
                "Briefly confirm to the user that the recipe has started."
            ),
        }
