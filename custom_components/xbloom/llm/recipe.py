"""Tools: list_xbloom_recipes and execute_xbloom_recipe."""
from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm

from ..coordinator import POUR_PATTERN_OPTIONS, WATER_SOURCE_TANK
from ..schema import compute_total_water_ml, find_recipe
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
    summary = {
        "uid": raw.get("uid"),
        "name": raw.get("name"),
        "source": raw.get("source"),
        "cup_type": raw.get("cup_type", "omni_dripper"),
        "dose_g": raw.get("dose_g"),
        "grind_size": raw.get("grind_size"),
        "total_water_ml": compute_total_water_ml(raw),
        "pour_count": len(pours),
    }
    if raw.get("cloud_table_id") is not None:
        summary["cloud_table_id"] = raw["cloud_table_id"]
    if raw.get("share_url"):
        summary["share_url"] = raw["share_url"]
    return summary


_RECIPE_ID_DESCRIPTION = (
    "Which recipe — its local uid, cloud table id, share URL/id, or exact "
    "name (from list_xbloom_recipes)."
)


def _resolve_or_error(coordinator, identifier: str):
    """find_recipe + the shared not-found tool response."""
    resolved = find_recipe(coordinator.recipes or {}, identifier)
    if resolved is not None:
        return resolved, None
    return None, {
        "success": False,
        "error": "recipe_not_found",
        "available_recipes": list((coordinator.recipes or {}).keys()),
        "instruction": (
            "Tell the user that recipe was not found and list the "
            "available recipes so they can pick one."
        ),
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
            "volume_ml": p.get("volume_ml"),
            "temperature_c": p.get("temperature_c"),
            "flow_rate": p.get("flow_rate", 3.0),
            "pattern": pat_name,
            "pause_seconds": p.get("pause_seconds", 0),
        })
    return {
        "name": raw.get("name"),
        "cup_type": raw.get("cup_type", "omni_dripper"),
        "grind_size": raw.get("grind_size"),
        "rpm": raw.get("rpm"),
        "dose_g": raw.get("dose_g"),
        "total_water_ml": compute_total_water_ml(raw),
        "bypass_volume_ml": raw.get("bypass_volume", 0),
        "bypass_temperature_c": raw.get("bypass_temperature", 0),
        "pours": pours,
    }


class XBloomGetRecipeTool(XBloomBaseTool):
    """Return the full configuration of one saved recipe."""

    name = "get_xbloom_recipe"
    description = (
        "Get the full configuration of one saved XBloom recipe: "
        "grind size, RPM, bean weight, total water, and every pour's "
        "volume, temperature, flow rate, and pour pattern (with 0-based "
        "pour_index). Use this before execute_xbloom_recipe when the user "
        "wants to tweak the grind, RPM, or any individual pour's volume / "
        "flow rate / pattern, so you know the current values and which "
        "pour_index to target."
    )
    parameters = vol.Schema(
        {
            vol.Required("recipe", description=_RECIPE_ID_DESCRIPTION): str,
        }
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> dict:
        resolved, err = _resolve_or_error(
            self.coordinator, tool_input.tool_args["recipe"]
        )
        if err:
            return err
        return {
            "success": True,
            "recipe": _detail_recipe(resolved[1]),
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
        "List every local XBloom recipe (the source of truth — what the "
        "Recipe dropdown shows), with a short summary of each: local uid, "
        "cup type, bean weight, total water, number of pours, and any "
        "cloud id / share URL if the recipe has been imported/exported."
    )
    parameters = vol.Schema(
        {
            vol.Optional(
                "query",
                description=(
                    "Filter to recipes whose name contains this text "
                    "(case-insensitive). Omit to list all."
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
        recipes = self.coordinator.recipes or {}
        query = (tool_input.tool_args.get("query") or "").strip().lower()
        rows = [
            _summarize_recipe(r)
            for name, r in recipes.items()
            if not query or query in name.lower()
        ]
        if not rows:
            return {
                "recipes": [],
                "instruction": (
                    "Tell the user no recipes matched. They can create one "
                    "with create_xbloom_recipe or import one from a share "
                    "link with import_xbloom_cloud_recipe."
                ),
            }
        return {
            "recipes": rows,
            "instruction": (
                "Read out the recipe names. Mention details only if the user "
                "asks for them."
            ),
        }


class XBloomExecuteRecipeTool(XBloomBaseTool):
    """Execute a saved recipe by name, after the user confirms beans are loaded."""

    name = "execute_xbloom_recipe"
    description = (
        "Execute a saved XBloom recipe. Any top-level scalar (grind_size, "
        "rpm, dose_g, ratio, cup_type, bypass) can be overridden for this "
        "brew only — the stored recipe is unchanged, and a dose/ratio "
        "override rescales the pour volumes proportionally. SAFETY: before calling this "
        "tool you MUST ask the user to confirm: (1) that beans (or tea "
        "leaves, for tea recipes) have been added, (2) that the dripper is "
        "attached, (3) for coffee only, that the paper coffee filter has "
        "been installed in the dripper (the machine cannot detect the "
        "filter on its own), and (4) that the cup or dripper is on the "
        "scale. Recipes that don't grind (dose_g or grind_size is 0/absent — "
        "check get_xbloom_recipe first — e.g. a water-only pour) skip the "
        "beans/dripper/filter confirmation entirely, since there are no "
        "grounds to add or catch; you can call this tool directly for those "
        "without asking. The tool can usually detect the cup automatically by its "
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
            vol.Required("recipe", description=_RECIPE_ID_DESCRIPTION): str,
            vol.Required(
                "beans_confirmed",
                description=(
                    "Set to true ONLY after the user has explicitly confirmed "
                    "that beans (or tea leaves) have been loaded. If you have "
                    "not yet asked the user, set this to false."
                ),
            ): bool,
            vol.Required(
                "dripper_confirmed",
                description=(
                    "Set to true ONLY after the user has explicitly confirmed "
                    "that the dripper is attached (coffee and tea recipes "
                    "both use it). Not needed for a no-grind recipe (see "
                    "tool description)."
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
                "dose_g",
                description=(
                    "Optional coffee-dose override in grams for this brew "
                    "only. Pour volumes are rescaled so total water stays "
                    "dose_g × ratio. Coffee recipes only."
                ),
            ): vol.All(vol.Coerce(float), vol.Range(min=1, max=100)),
            vol.Optional(
                "ratio",
                description=(
                    "Optional water-ratio override (total water = dose_g × "
                    "ratio) for this brew only. Pour volumes are rescaled "
                    "to match. Coffee recipes only."
                ),
            ): vol.All(vol.Coerce(float), vol.Range(min=1, max=50)),
            vol.Optional(
                "cup_type",
                description=(
                    "Optional cup/brewer type override for this brew only."
                ),
            ): vol.In(["x_pod", "omni_dripper", "other", "tea"]),
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

    async def _async_try_prearm(self, recipe_name: str, has_overrides: bool) -> bool:
        """Best-effort pre-arm before a confirmation ask (T13): load the
        recipe on the machine so its start prompt is showing while the
        user is asked. Skipped for override-carrying calls (the armed
        payload uses stored settings only) and when an arm is already
        standing. Returns whether an arm is in place afterwards."""
        if has_overrides:
            return False
        if self.coordinator._armed_operation == "recipe":
            return True
        try:
            self.coordinator.select_recipe(recipe_name)
            await self.coordinator.async_arm_recipe()
        except Exception as exc:
            _LOGGER.debug("recipe pre-arm failed (best-effort): %s", exc)
        return self.coordinator._armed_operation == "recipe"

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> dict:
        beans_confirmed = bool(tool_input.tool_args["beans_confirmed"])
        dripper_confirmed = bool(tool_input.tool_args["dripper_confirmed"])
        filter_confirmed = bool(tool_input.tool_args["filter_confirmed"])
        cup_confirmed = bool(tool_input.tool_args["cup_confirmed"])

        resolved, err = _resolve_or_error(
            self.coordinator, tool_input.tool_args["recipe"]
        )
        if err:
            return err
        recipe_name, recipe = resolved
        cup_type = (recipe.get("cup_type") or "omni_dripper").lower()
        is_tea = cup_type == "tea"
        ingredient = "tea leaves" if is_tea else "beans"

        # A recipe with no dose/grind (e.g. a water-only "pour" recipe)
        # never grinds coffee, so there are no grounds to hold beans or
        # catch in a filter — mirrors the `grinding` check coordinator.py /
        # brewing.py use to decide whether to send the grind command at all.
        needs_grind = (
            not is_tea
            and float(recipe.get("dose_g", 0) or 0) > 0
            and int(recipe.get("grind_size", 0) or 0) > 0
        )

        missing: list[str] = []
        if is_tea or needs_grind:
            if not beans_confirmed:
                missing.append(ingredient)
            if not dripper_confirmed:
                missing.append("dripper")
            if needs_grind and not filter_confirmed:
                missing.append("paper coffee filter")

        # Per-call overrides make the arm/confirm path unusable: the armed
        # payload always carries the recipe's STORED settings, so a
        # confirm would silently ignore them (T13).
        has_overrides = bool(
            {"grind_size", "rpm", "bypass_volume", "bypass_temperature",
             "dose_g", "ratio", "cup_type"} & tool_input.tool_args.keys()
            or tool_input.tool_args.get("pour_overrides")
        )

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

        if missing:
            items = " and ".join(missing)
            confirmed_flags = {
                ingredient: "beans_confirmed",
                "dripper": "dripper_confirmed",
                "paper coffee filter": "filter_confirmed",
            }
            retry_flags = " and ".join(
                f"{confirmed_flags[item]}=true" for item in missing
            )
            armed = await self._async_try_prearm(recipe_name, has_overrides)
            return {
                "success": False,
                "confirmation_required": True,
                "missing_confirmations": missing,
                "recipe": _summarize_recipe(recipe),
                "instruction": (
                    f"Do NOT start the recipe yet. "
                    + (
                        "The machine has loaded the recipe and is showing "
                        "its start prompt. "
                        if armed
                        else ""
                    )
                    + f"Ask the user to confirm "
                    f"that the {items} have been added/installed for the "
                    f"'{recipe_name}' recipe. The machine cannot detect the "
                    f"filter on its own, so the user must verify it manually. "
                    f"Once they confirm, call execute_xbloom_recipe again "
                    f"with {retry_flags}."
                ),
            }

        # Cup presence: weight > threshold proves a cup is there. A reading
        # near 0 g is ambiguous because the machine auto-tares any weight
        # present at power-on, so a cup placed before boot reads as 0 g.
        # When ambiguous, fall back to a manual user confirmation.
        weight = float((self.coordinator.data or {}).get("weight", 0.0) or 0.0)
        cup_on_scale = weight >= CUP_PRESENCE_WEIGHT_G
        if not cup_on_scale and not cup_confirmed:
            armed = await self._async_try_prearm(recipe_name, has_overrides)
            return {
                "success": False,
                "error": "cup_unverified",
                "scale_weight_g": weight,
                "instruction": (
                    "Do NOT start the recipe yet. "
                    + (
                        "The machine has loaded the recipe and is showing "
                        "its start prompt. "
                        if armed
                        else ""
                    )
                    + "The scale reads "
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
        overrides = {
            key: args[key]
            for key in ("dose_g", "ratio", "cup_type")
            if key in args
        }

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
            if self.coordinator._armed_operation == "recipe" and not has_overrides:
                # A standing pre-arm from the confirmation ask (T13) —
                # confirm it instead of re-executing the whole chain.
                await self.coordinator.async_confirm_recipe()
            else:
                if self.coordinator._armed_operation == "recipe":
                    # Overrides arrived after a pre-arm: the armed payload
                    # carries stored settings only — back out first.
                    await self.coordinator.async_cancel()
                await self.coordinator.async_execute_recipe(
                    overrides=overrides or None,
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
