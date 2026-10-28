"""Tools: xbloom__list_recipes and xbloom__execute_recipe."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm

from custom_components.xbloom.coordinator import (
    POUR_PATTERN_OPTIONS,
    WATER_SOURCE_TANK,
    XBloomCoordinator,
)
from custom_components.xbloom.schema import compute_total_water_ml, find_recipe

from .base import XBloomBaseTool

_LOGGER = logging.getLogger(__name__)

# Minimum scale weight (g) used to detect that a cup/dripper is sitting on
# the platform. Tare drift typically stays under 5 g; a real cup or dripper
# sits well above this floor.
CUP_PRESENCE_WEIGHT_G = 20.0

# int → name, for surfacing pour patterns to the LLM in xbloom__get_recipe.
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
    "name (from xbloom__list_recipes)."
)


def _resolve_or_error(
    coordinator: XBloomCoordinator, identifier: str
) -> tuple[tuple[str, dict] | None, dict | None]:
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
    pour_index in xbloom__execute_recipe's pour_overrides is 0-based to
    match the order returned here.
    """
    pours = []
    for i, p in enumerate(raw.get("pours") or []):
        pat = p.get("pattern", 2)
        if isinstance(pat, str):
            pat_name = pat.strip().lower()
        else:
            pat_name = _PATTERN_INT_TO_NAME.get(int(pat), "spiral")
        pours.append(
            {
                "pour_index": i,
                "volume_ml": p.get("volume_ml"),
                "temperature_c": p.get("temperature_c"),
                "flow_rate": p.get("flow_rate", 3.0),
                "pattern": pat_name,
                "pause_seconds": p.get("pause_seconds", 0),
            }
        )
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

    name = "xbloom__get_recipe"
    title = "Get xBloom recipe"
    annotations = llm.ToolAnnotations(
        read_only=True, destructive=False, idempotent=True, open_world=False
    )
    description = (
        "Get the full configuration of one saved xBloom recipe: "
        "grind size, RPM, bean weight, total water, and every pour's "
        "volume, temperature, flow rate, and pour pattern (with 0-based "
        "pour_index). Use this before xbloom__execute_recipe when the user "
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
    ) -> llm.ToolResult:
        resolved, err = _resolve_or_error(self.coordinator, tool_input.tool_args["recipe"])
        if err:
            return llm.ToolResult(data=err, error=True)
        return llm.ToolResult(
            data={
                "success": True,
                "recipe": _detail_recipe(resolved[1]),
                "instruction": (
                    "Use these values to decide any grind_size / rpm / "
                    "pour_overrides you pass to xbloom__execute_recipe. Only "
                    "override what the user asked to change."
                ),
            }
        )


class XBloomListRecipesTool(XBloomBaseTool):
    """List recipes configured for this machine."""

    name = "xbloom__list_recipes"
    title = "List xBloom recipes"
    annotations = llm.ToolAnnotations(
        read_only=True, destructive=False, idempotent=True, open_world=False
    )
    description = (
        "List every local xBloom recipe (the source of truth — what the "
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
    ) -> llm.ToolResult:
        recipes = self.coordinator.recipes or {}
        query = (tool_input.tool_args.get("query") or "").strip().lower()
        rows = [
            _summarize_recipe(r)
            for name, r in recipes.items()
            if not query or query in name.lower()
        ]
        if not rows:
            return llm.ToolResult(
                data={
                    "recipes": [],
                    "instruction": (
                        "Tell the user no recipes matched. They can create one "
                        "with xbloom__create_recipe or import one from a share "
                        "link with xbloom__import_cloud_recipe."
                    ),
                }
            )
        return llm.ToolResult(
            data={
                "recipes": rows,
                "instruction": (
                    "Read out the recipe names. Mention details only if the user asks for them."
                ),
            }
        )


class XBloomExecuteRecipeTool(XBloomBaseTool):
    """Arm a saved recipe on the machine, then start it once the user confirms."""

    name = "xbloom__execute_recipe"
    title = "Execute xBloom recipe"
    annotations = llm.ToolAnnotations(
        read_only=False, destructive=True, idempotent=False, open_world=True
    )
    description = (
        "Execute a saved xBloom recipe. Two-phase flow: the first call "
        "(without confirmed) ARMS the machine — it loads the recipe and "
        "shows its start prompt without brewing — and returns a checklist "
        "(beans or tea leaves, dripper, paper filter, cup) to ask the user "
        "about. Call again with confirmed=true once the user confirms; if "
        "they decline, call xbloom__cancel. confirmed=true only starts a "
        "recipe that is still armed — otherwise it arms again and you must "
        "ask again. Any top-level scalar (grind_size, rpm, dose_g, ratio, "
        "cup_type, bypass) can be overridden for this brew only — the "
        "stored recipe is unchanged, and a dose/ratio override rescales the "
        "pour volumes proportionally. Overrides are applied when arming: "
        "pass them on the first call; to change them, call again without "
        "confirmed. Water level is checked automatically — the tool refuses "
        "to arm and returns error='water_low' if the tank needs a refill "
        "(skipped when the Water Source select is 'direct', a hose feed)."
    )
    parameters = vol.Schema(
        {
            vol.Required("recipe", description=_RECIPE_ID_DESCRIPTION): str,
            vol.Optional(
                "confirmed",
                default=False,
                description=(
                    "Set to true ONLY after the user has confirmed every "
                    "item of the checklist the first (arming) call returned "
                    "and wants to start the brew."
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
                description=("Optional cup/brewer type override for this brew only."),
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
                    "xbloom__get_recipe) and any of: volume (30-500 ml), "
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
    ) -> llm.ToolResult:
        args = tool_input.tool_args
        confirmed = bool(args.get("confirmed", False))

        resolved, err = _resolve_or_error(self.coordinator, args["recipe"])
        if err:
            return llm.ToolResult(data=err, error=True)
        recipe_name, recipe = resolved
        cup_type = (args.get("cup_type") or recipe.get("cup_type") or "omni_dripper").lower()
        is_tea = cup_type == "tea"
        ingredient = "tea leaves" if is_tea else "beans"

        # A recipe with no dose/grind (e.g. a water-only "pour" recipe)
        # never grinds coffee, so there are no grounds to hold beans or
        # catch in a filter — mirrors the `grinding` check coordinator.py /
        # brewing.py use to decide whether to send the grind command at all.
        needs_grind = (
            not is_tea
            and float(args.get("dose_g", recipe.get("dose_g", 0)) or 0) > 0
            and int(recipe.get("grind_size", 0) or 0) > 0
        )

        client = self.coordinator.client
        if client is None or not client.is_connected:
            try:
                ok = await self.coordinator.async_connect()
            except Exception as exc:
                _LOGGER.exception("auto-connect before recipe failed: %s", exc)
                ok = False
            if not ok:
                return llm.ToolResult(
                    data={
                        "success": False,
                        "error": "connect_failed",
                        "instruction": (
                            "Tell the user the xBloom could not be reached over "
                            "Bluetooth. Ask them to check the machine is powered "
                            "on and in range."
                        ),
                    },
                    error=True,
                )

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
            return llm.ToolResult(
                data={
                    "success": False,
                    "error": "water_low",
                    "instruction": (
                        "Do NOT start the recipe. Tell the user the xBloom's "
                        "water tank is low and ask them to refill it before "
                        "brewing. Do not retry until they confirm it's refilled."
                    ),
                },
                error=True,
            )

        # Phase 2: only a standing arm of THIS recipe can be started. The
        # overrides were baked into the armed payload, so any repeated on
        # this call are ignored.
        if (
            confirmed
            and self.coordinator._armed_operation == "recipe"
            and self.coordinator.selected_recipe == recipe_name
        ):
            try:
                await self.coordinator.async_confirm_recipe()
            except Exception as exc:
                _LOGGER.exception("xbloom__execute_recipe failed: %s", exc)
                return llm.ToolResult(
                    data={
                        "success": False,
                        "error": f"Execution failed: {exc!s}",
                    },
                    error=True,
                )
            self.coordinator.async_update_listeners()
            return llm.ToolResult(
                data={
                    "success": True,
                    "recipe": _summarize_recipe(recipe),
                    "instruction": ("Briefly confirm to the user that the recipe has started."),
                }
            )

        # Phase 1: arm. Select the recipe (also syncs the grind/RPM sliders
        # to it for coffee grinding recipes), then layer any explicit
        # overrides on top.
        self.coordinator.select_recipe(recipe_name)

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
        overrides = {key: args[key] for key in ("dose_g", "ratio", "cup_type") if key in args}

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
            if self.coordinator._armed_operation:
                # A standing arm (another recipe, stale overrides, or a
                # grind/pour) — back out of its screen before re-arming.
                await self.coordinator.async_cancel()
            await self.coordinator.async_arm_recipe(
                overrides=overrides or None,
                pour_overrides=pour_overrides or None,
                bypass_volume=bypass_volume,
                bypass_temperature=bypass_temperature,
            )
        except Exception as exc:
            _LOGGER.exception("xbloom__execute_recipe arm failed: %s", exc)
            return llm.ToolResult(
                data={
                    "success": False,
                    "error": f"Arming failed: {exc!s}",
                },
                error=True,
            )

        # Reflect the selection on the select entity.
        self.coordinator.async_update_listeners()

        if self.coordinator._armed_operation != "recipe":
            # async_arm_recipe logs and swallows BLE failures.
            return llm.ToolResult(
                data={
                    "success": False,
                    "error": "arm_failed",
                    "instruction": (
                        "Tell the user the recipe could not be loaded on the "
                        "xBloom. Nothing was started."
                    ),
                },
                error=True,
            )

        # The checklist for the user. Cup presence: weight above the
        # threshold proves a cup is there; a reading near 0 g is ambiguous
        # because the machine auto-tares any weight present at power-on, so
        # a cup placed before boot reads as 0 g.
        checklist: list[str] = []
        if is_tea or needs_grind:
            checklist.append(f"{ingredient} added")
            checklist.append("dripper attached")
        if needs_grind:
            checklist.append(
                "paper coffee filter installed (the machine cannot detect it)"
            )
        weight = float((self.coordinator.data or {}).get("weight", 0.0) or 0.0)
        if weight < CUP_PRESENCE_WEIGHT_G:
            checklist.append(
                f"cup or dripper on the scale (the scale reads {weight:.1f} g — "
                "either nothing is on it, or it was placed before power-on "
                "and tared to 0 g)"
            )
        return llm.ToolResult(
            data={
                "success": True,
                "armed": True,
                "confirmation_required": True,
                "checklist": checklist,
                "recipe": _summarize_recipe(recipe),
                "instruction": (
                    (
                        "The recipe has NOT started: there was no standing arm "
                        "of it to confirm, so the machine was armed again. "
                        if confirmed
                        else ""
                    )
                    + "The machine has loaded the recipe and is showing its "
                    "start prompt. Ask the user to confirm "
                    + (": " + "; ".join(checklist) + ". " if checklist else "starting it. ")
                    + "If they confirm, call xbloom__execute_recipe again with "
                    "the same recipe and confirmed=true. If they decline, call "
                    "xbloom__cancel."
                ),
            }
        )
