"""Recipe execution, Easy Mode slot writes, local recipe store CRUD, and
cloud import/export/search.

Part of the coordinator package split (Phase 3, structural only — see
constants.py's module docstring).
"""
from __future__ import annotations

import copy
import logging
from typing import Any, Dict, List, Optional

import voluptuous as vol

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import service as service_helper

from .. import brewing
from .._cloud_client import (
    cloud_recipe_to_local,
    local_recipe_to_cloud,
    validate_pour_volume_consistency,
)
from ..ble.models import CupType, PourPattern, PourStep, VibrationPattern, XBloomRecipe
from ..const import (
    CONF_ACCOUNT_RECIPES_SEEDED,
    CONF_EASY_SLOTS,
    CONF_RECIPES,
    CONF_RECIPES_SEEDED,
    DATA_COORDINATOR,
    DOMAIN,
)
from ..schema import (
    RECIPE_SCHEMA,
    compute_total_water_ml,
    dedupe_name,
    find_recipe,
    new_recipe_uid,
    scale_pours_to_total,
    strip_protected_recipe_fields,
)
from .constants import (
    _CLOUD_EDIT_PRESERVE_KEYS,
    _OFFICIAL_RECIPE_SYNC_LIMIT,
    MIN_FIRMWARE_EASY_MODE,
    MIN_FIRMWARE_TEA,
    WATER_SOURCE_TANK,
    _firmware_at_least,
)

_LOGGER = logging.getLogger(__name__)

_YAML_CUP_TYPE_MAP = {
    "x_pod": int(CupType.X_POD),
    "xpod": int(CupType.X_POD),
    "omni_dripper": int(CupType.OMNI_DRIPPER),
    "other": int(CupType.OTHER),
    "tea": int(CupType.TEA),
}

_YAML_VIBRATION_MAP = {
    "none": VibrationPattern.NONE,
    "before": VibrationPattern.BEFORE,
    "after": VibrationPattern.AFTER,
    "both": VibrationPattern.BOTH,
}


def _build_recipe_from_yaml(raw: dict) -> XBloomRecipe:
    """Build an XBloomRecipe from a validated YAML recipe dict.

    Bypasses xbloom.models.recipes.parse_recipe_json because that helper
    expects the upstream JSON shape (camelCase keys, `dose`, `cupType`)
    and treats `grind_size: 0` / `bean_weight: 0` as missing via `or`,
    silently substituting defaults — which routes tea recipes (no grind,
    no beans) into the coffee brew path.

    Reads the local schema's cloud-shaped field names (``dose_g``,
    ``ratio``, ``pours[].volume_ml/temperature_c/pause_seconds``) but
    still constructs the vendored ``XBloomRecipe``/``PourStep`` with
    THEIR field names (``bean_weight``, ``total_water``, ``volume``,
    ``temperature``, ``pausing``) — that vendored class is untouched, so
    the translation happens only here.
    """
    cup_raw = raw.get("cup_type", 0)
    if isinstance(cup_raw, str):
        cup_val = _YAML_CUP_TYPE_MAP.get(cup_raw.strip().lower(), 0)
    else:
        cup_val = int(cup_raw)

    pours: List[PourStep] = []
    for p in raw.get("pours", []):
        vib_raw = p.get("vibration", "none")
        vib = (
            _YAML_VIBRATION_MAP.get(vib_raw.strip().lower(), VibrationPattern.NONE)
            if isinstance(vib_raw, str)
            else VibrationPattern(int(vib_raw))
        )
        pours.append(
            PourStep(
                volume=int(p["volume_ml"]),
                temperature=int(p["temperature_c"]),
                flow_rate=float(p.get("flow_rate", 3.0)),
                pausing=int(p.get("pause_seconds", 0)),
                pattern=PourPattern(int(p.get("pattern", 2))),
                vibration=vib,
            )
        )

    # total_water = dose_g * ratio (matches the XBloom cloud API's own
    # dose/grandWater relationship), rounded to the nearest ml to absorb
    # float drift from a repeating-decimal ratio. Falls back to summing
    # pour volumes when ratio/dose_g can't produce a total (tea recipes
    # have no weighed dose) — see schema.compute_total_water_ml, shared
    # so this and the LLM-facing recipe summary can't disagree on the
    # actual brewed total. A zero footer byte 2 causes the machine to
    # skip grinding (hot water only) on Easy Mode slots and may also
    # confuse live brew, so the fallback still matters here.
    total_water = int(round(compute_total_water_ml(raw)))

    return XBloomRecipe(
        grind_size=int(raw.get("grind_size", 0)),
        total_water=total_water,
        rpm=int(raw.get("rpm", 80)),
        cup_type=cup_val,
        name=str(raw.get("name", "Unknown")),
        bean_weight=float(raw.get("dose_g", 0.0)),
        pours=pours,
    )


def _apply_pour_overrides(recipe: XBloomRecipe, overrides: List[dict]) -> None:
    """Override individual pours' volume / flow_rate / pattern by index.

    Each entry is a dict with a 0-based ``pour_index`` plus any of
    ``volume`` / ``flow_rate`` / ``pattern`` (pattern as an int 0/1/2).
    Used by the LLM execute tool so an agent can tweak single pours
    without rewriting the saved recipe. Out-of-range indexes are skipped.
    The dataclass validates only at construction, so callers are
    responsible for passing in-range values (the tool schema enforces it).
    """
    for ov in overrides:
        idx = int(ov.get("pour_index", -1))
        if not 0 <= idx < len(recipe.pours):
            continue
        pour = recipe.pours[idx]
        if ov.get("volume") is not None:
            pour.volume = int(ov["volume"])
        if ov.get("flow_rate") is not None:
            pour.flow_rate = float(ov["flow_rate"])
        if ov.get("pattern") is not None:
            pour.pattern = PourPattern(int(ov["pattern"]))


class RecipesMixin:
    """Recipe selection/execution, Easy Mode slots, local store CRUD, cloud."""

    def select_recipe(self, name: Optional[str]) -> None:
        """Set the active recipe and sync the grind/RPM sliders to it.

        Only coffee recipes that actually grind push their grind_size /
        rpm onto the number entities — tea and no-grind recipes leave the
        sliders untouched (they don't grind, so their values are
        meaningless and would clobber the user's manual-grind settings).
        After syncing, the number entities are the source of truth: the
        user can tweak them and :meth:`async_execute_recipe` will brew
        with the tweaked values. (Bypass is recipe-scoped, not a slider —
        it stays on the YAML value unless overridden per brew.)
        """
        self.selected_recipe = name
        raw = (self.recipes or {}).get(name) if name else None
        if not raw:
            return
        cup = raw.get("cup_type", "omni_dripper")
        is_tea = str(cup).strip().lower() == "tea" or cup == int(CupType.TEA)
        grind = int(raw.get("grind_size", 0) or 0)
        if is_tea or grind <= 0:
            return
        self.grind_size = grind
        self.rpm = int(raw.get("rpm", self.rpm) or self.rpm)
        self.async_update_listeners()

    async def async_execute_recipe(
        self,
        *,
        overrides: Optional[dict] = None,
        pour_overrides: Optional[List[dict]] = None,
        bypass_volume: Optional[float] = None,
        bypass_temperature: Optional[float] = None,
    ) -> None:
        """Execute the currently selected YAML recipe.

        Routing lives in :mod:`brewing`. Coffee uses an inline sequence
        (mirrors brAzzi64/xbloom-ble) that threads bypass_volume /
        bypass_temperature into the 8102 packet; tea (cup_type=4) takes
        the separate tea sequence. See brewing.py.

        For coffee grinding recipes the live ``grind_size`` / ``rpm``
        number values override the YAML — :meth:`select_recipe` keeps
        them in sync with the recipe, so by execute time they hold either
        the recipe value or the user's tweak. Tea / no-grind recipes are
        brewed as configured. ``bypass_volume`` / ``bypass_temperature``
        (service / LLM only) override the recipe's bypass for this brew —
        ``None`` means use the recipe's YAML value; bypass can be added to
        a recipe that has none. Tea always brews with bypass off.
        ``pour_overrides`` (LLM-only) tweaks individual pours' volume /
        flow_rate / pattern.

        ``overrides`` replaces top-level recipe scalars (``dose_g`` /
        ``ratio`` / ``cup_type``) for this brew only — the stored recipe
        is untouched. Changing ``dose_g``/``ratio`` changes the total
        brew water, so the pours are proportionally rescaled to keep
        ``sum(pours) + bypass == dose_g * ratio`` (the machine's own
        invariant). Grind/RPM overrides go through the number-entity
        values above instead.
        """
        if not self._check_connected():
            return
        # Check water BEFORE touching the machine (mode switch, BLE writes,
        # etc.) — without this, a low-water recipe attempt runs the whole
        # brew sequence and only fails once the firmware fires
        # RD_ErrorLackOfWater, so the user finds out mid-attempt instead of
        # up front. Skipped when the user has told us they're on a direct
        # (hose) feed: water_level_ok tracks the internal tank sensor, which
        # stays empty/unreliable by design on a hose setup and would
        # otherwise block every brew. (This is the same water_source select
        # that otherwise only affects manual pour — here it's just the
        # user's declaration of which feed is actually plumbed in.)
        if self.water_source == WATER_SOURCE_TANK and not self.data.get(
            "water_level_ok", True
        ):
            raise HomeAssistantError(
                "XBloom water level is too low — refill the tank before brewing."
            )
        if not self.selected_recipe or self.selected_recipe not in self.recipes:
            _LOGGER.warning("No valid recipe selected (%s)", self.selected_recipe)
            return
        # Tea (cmd 4512/4513) doesn't exist on firmware older than
        # V12.0D.300 — the machine would silently ignore it rather than
        # refuse cleanly, so check before touching the machine at all
        # (mode switch included). See MIN_FIRMWARE_TEA's docstring above.
        raw_cup_type = self.recipes[self.selected_recipe].get("cup_type")
        if overrides and "cup_type" in overrides:
            raw_cup_type = overrides["cup_type"]
        if str(raw_cup_type).lower() == "tea" and not _firmware_at_least(
            self.data.get("version"), MIN_FIRMWARE_TEA
        ):
            raise HomeAssistantError(
                f"Tea recipes require XBloom firmware {MIN_FIRMWARE_TEA} or newer "
                f"(current: {self.data.get('version') or 'unknown'})."
            )
        try:
            # ── Auto-switch to PRO mode if the machine is in Easy mode ──
            # Easy Mode silences or misinterprets the 8001/8004/8002 Pro-mode
            # brew sequence, resulting in hot water only (grinder never runs).
            # We always switch to PRO before a live brew to guarantee the
            # sequence is honoured.  The user can switch back via the Mode
            # switch entity if they want physical slot buttons afterwards.
            await self._ensure_pro_mode()
            raw = self.recipes[self.selected_recipe]
            if overrides:
                raw = {**raw, **overrides}
                if "dose_g" in overrides or "ratio" in overrides:
                    dose = float(raw.get("dose_g", 0) or 0)
                    ratio = raw.get("ratio")
                    if dose > 0 and ratio:
                        effective_bypass = (
                            float(raw.get("bypass_volume", 0.0) or 0.0)
                            if bypass_volume is None else float(bypass_volume)
                        )
                        raw["pours"] = scale_pours_to_total(
                            raw.get("pours", []),
                            dose * float(ratio) - effective_bypass,
                        )
            recipe = _build_recipe_from_yaml(raw)
            is_tea = brewing.is_tea_recipe(recipe)
            if not is_tea and recipe.grind_size > 0:
                recipe.grind_size = int(self.grind_size)
                recipe.rpm = int(self.rpm)
            if pour_overrides:
                _apply_pour_overrides(recipe, pour_overrides)
            # Snapshot the final (post-override, post-rescale) pour list so
            # the "bloom" handler in _dispatch_event can look up each
            # pour's actual flow_rate as the brew progresses.
            self._active_recipe_pours = recipe.pours
            self._executing_recipe = True
            self._active_operation = "recipe"
            self.current_pour_index = None
            # Bypass — coffee only. Default to the recipe's YAML value;
            # an explicit override (service / LLM) wins. The tea sequence
            # forces bypass off internally, so tea always passes 0/0.
            if is_tea:
                bypass_vol = bypass_temp = 0.0
            else:
                bypass_vol = (
                    float(raw.get("bypass_volume", 0.0) or 0.0)
                    if bypass_volume is None else float(bypass_volume)
                )
                bypass_temp = (
                    float(raw.get("bypass_temperature", 0.0) or 0.0)
                    if bypass_temperature is None else float(bypass_temperature)
                )
            # Sleep-retry wrapped (2026-07-18) — see coordinator.
            # connection._async_retry_while_sleeping's docstring. If the
            # machine was asleep, none of this sequence's writes took
            # effect, so retrying the whole thing from the top is safe.
            await self._async_retry_while_sleeping(
                lambda: brewing.async_execute_recipe(
                    self.client, recipe,
                    bypass_volume=bypass_vol,
                    bypass_temperature=bypass_temp,
                )
            )
        except Exception as exc:
            _LOGGER.error("Recipe execute error: %s", exc, exc_info=True)
            self._executing_recipe = False
            self._active_recipe_pours = None
            self._active_operation = None

    async def async_write_easy_slot(
        self, slot_letter: str, identifier: Optional[str] = None
    ) -> dict:
        """Write a recipe to Easy Mode slot A/B/C (11510, type-2 packet).

        ``identifier`` (uid / cloud table id / share URL/id / name)
        selects the recipe; omitted, the currently-selected recipe (the
        Recipe ``select`` entity) is written — that's what the slot
        button entities do. A share URL/id not present locally is
        auto-imported first (clone + uid), so "write this shared recipe
        to slot B" is one call. On success **only the target letter's**
        slot → recipe mapping is persisted in ``entry.options["easy_slots"]``
        so the slot text entities can show (and restore) what HA last
        *intentionally* wrote; the machine itself never reports slot
        contents.

        Live-verified 2026-07-15 (cross-referenced against
        Janczykkkko/xbloom-ble's independent capture): the machine only
        *persists* a slot when all three (A/B/C) are written together —
        writing one alone leaves it hung at "saving" (RETRY) — and only
        accepts slot writes in Pro Mode. So this call fills in the other
        two slots from ``entry.options["easy_slots"]`` (falling back to
        the target recipe for a slot HA has never written — the machine
        has no readback, so there's nothing else to preserve it with),
        force-switches to Pro Mode if needed, writes all three, then
        restores whatever mode the machine was in before. That fallback
        recipe *is* sent to the machine for an unwritten slot (there's no
        other valid payload to send), but it is deliberately **not**
        recorded as that slot's own assignment — otherwise the first
        write to any slot would make every other never-configured slot's
        sensor falsely flip from unknown to "registered" too (hardware-
        confirmed 2026-07-17: writing only slot A with B/C both unknown
        made all three sensors show as registered).
        """
        if identifier:
            resolved = find_recipe(self.recipes or {}, identifier)
            if resolved is None and self._looks_like_share_ref(str(identifier)):
                imported = await self.async_import_cloud_recipe(str(identifier))
                if not imported.get("success"):
                    return imported
                resolved = find_recipe(self.recipes or {}, imported["uid"])
            if resolved is None:
                return {
                    "success": False,
                    "error": "recipe_not_found",
                    "message": f"No local recipe matches {identifier!r}.",
                }
            name, raw = resolved
        else:
            name = self.selected_recipe
            if not name or name not in (self.recipes or {}):
                _LOGGER.warning(
                    "Easy slot write ignored — no recipe selected (%s)", name
                )
                return {
                    "success": False,
                    "error": "no_recipe_selected",
                    "message": "No recipe is selected.",
                }
            raw = self.recipes[name]

        # Easy Mode slots (11510) are payload-identical to the coffee-only
        # 8001/8004 auto-brew recipe blob (brewing.async_write_easy_slots
        # builds them with the same _build_coffee_recipe_payload used
        # there) — there is no dedicated tea slot format, and 8004 itself
        # is hardware-confirmed to NOT enter tea mode (see AGENTS.md's tea
        # firmware-quirks entry). So a tea recipe written to a slot can
        # never brew as real tea from the physical button — at best it
        # silently runs as a flat no-siphon multi-pour, and at worst (if
        # the recipe's grind_size/dose_g were left at RECIPE_SCHEMA's
        # coffee-oriented defaults, 50/15.0g, instead of explicitly zeroed)
        # it grinds beans for a tea recipe, which is what this check exists
        # to catch. Checked before any BLE traffic (mode switch included).
        if str(raw.get("cup_type", "")).strip().lower() == "tea":
            _LOGGER.warning(
                "Easy slot write refused — %r is a tea recipe, Easy Mode "
                "slots can't brew tea correctly", name,
            )
            return {
                "success": False,
                "error": "tea_not_supported_in_easy_slot",
                "message": (
                    f"{name!r} is a tea recipe — Easy Mode slots can't brew "
                    "tea correctly (no dedicated tea slot format on this "
                    "firmware). Use the execute_tea_recipe service or the "
                    "Recipe select entity + manual brew instead."
                ),
            }

        if not self._check_connected():
            return {
                "success": False,
                "error": "not_connected",
                "message": "The XBloom is not connected over Bluetooth.",
            }

        # Auto/Easy Mode (cmd 11510/11511/11512) doesn't exist on firmware
        # older than V12.0D.210 — check before any mode-switch/slot-write
        # BLE traffic. See MIN_FIRMWARE_EASY_MODE's docstring above.
        if not _firmware_at_least(self.data.get("version"), MIN_FIRMWARE_EASY_MODE):
            return {
                "success": False,
                "error": "firmware_too_old",
                "message": (
                    f"Easy Mode requires XBloom firmware {MIN_FIRMWARE_EASY_MODE} "
                    f"or newer (current: {self.data.get('version') or 'unknown'})."
                ),
            }

        target_letter = slot_letter.strip().upper()
        if target_letter not in ("A", "B", "C"):
            return {
                "success": False,
                "error": "invalid_slot",
                "message": f"slot must be A, B, or C — got {slot_letter!r}",
            }

        # Fill in the other two slots from our own record of what HA last
        # wrote (the machine can't be asked what's actually there). A
        # slot HA has never written mirrors the target recipe rather than
        # being left as an unknown/blank.
        slot_names = {target_letter: name}
        slot_raws = {target_letter: raw}
        for other in ("A", "B", "C"):
            if other == target_letter:
                continue
            contents = self.easy_slot_contents(other)
            other_resolved = (
                find_recipe(self.recipes or {}, contents["uid"])
                if contents and contents.get("uid") else None
            )
            if other_resolved:
                slot_names[other], slot_raws[other] = other_resolved
            else:
                slot_names[other], slot_raws[other] = name, raw

        try:
            slot_recipes = {
                letter: _build_recipe_from_yaml(slot_raws[letter])
                for letter in ("A", "B", "C")
            }
        except Exception as exc:
            _LOGGER.error(
                "Easy slot write error building recipes (%s): %s",
                target_letter, exc, exc_info=True,
            )
            return {
                "success": False,
                "error": "write_failed",
                "message": f"Slot write failed: {exc}",
            }

        switched_to_pro = False
        try:
            if (self.data or {}).get("mode", "pro") == "easy":
                await self._async_switch_mode_with_retry("pro")
                switched_to_pro = True

            # Sleep-retry wrapped (2026-07-18) — see coordinator.
            # connection._async_retry_while_sleeping's docstring.
            await self._async_retry_while_sleeping(
                lambda: brewing.async_write_easy_slots(self.client, slot_recipes)
            )
        except Exception as exc:
            _LOGGER.error(
                "Easy slot write error (%s): %s", target_letter, exc, exc_info=True
            )
            return {
                "success": False,
                "error": "write_failed",
                "message": f"Slot write failed: {exc}",
            }
        finally:
            if switched_to_pro:
                try:
                    await self._async_switch_mode_with_retry("easy")
                    await self.async_refresh()
                except Exception as exc:
                    _LOGGER.warning("Restoring Easy Mode after slot write failed: %s", exc)

        entry = self.hass.config_entries.async_get_entry(self.entry_id)
        if entry is not None:
            slots = dict(entry.options.get(CONF_EASY_SLOTS) or {})
            # Only the target letter was actually requested by the user —
            # the other two were mirrored purely to satisfy the hardware's
            # all-three-at-once write requirement above. Recording them
            # here too would make untouched slots' sensors falsely show as
            # "registered" the first time any slot is written.
            slots[target_letter] = {
                "uid": slot_raws[target_letter].get("uid"),
                "name": slot_names[target_letter],
            }
            new_options = dict(entry.options)
            new_options[CONF_EASY_SLOTS] = slots
            self.hass.config_entries.async_update_entry(entry, options=new_options)
        self.async_update_listeners()
        return {"success": True, "slot": target_letter, "name": name,
                "uid": raw.get("uid")}

    def easy_slot_contents(self, slot_letter: str) -> Optional[dict]:
        """What HA last wrote to a slot — ``{"uid", "name"}`` or None."""
        entry = self.hass.config_entries.async_get_entry(self.entry_id)
        if entry is None:
            return None
        slots = entry.options.get(CONF_EASY_SLOTS) or {}
        return slots.get(slot_letter.upper())

    # ------------------------------------------------------------------
    # Cloud account (recipe sync) — all optional, never required for BLE use
    # ------------------------------------------------------------------

    @property
    def cloud_login_configured(self) -> bool:
        """Whether an XBloom cloud email/password were set up.

        Only gates AUTHENTICATED cloud calls (search/create/edit/delete —
        added in a later phase). Does NOT gate :meth:`async_import_cloud_recipe`
        — fetching a shared recipe needs no login at all on the wire.
        """
        return bool(self._cloud_email and self._cloud_password)

    async def async_ensure_cloud_login(self) -> bool:
        """Log in if an account is configured and not already logged in.

        Returns False (never raises) when no account is configured or the
        login itself fails — callers should turn that into a structured
        error rather than let an exception propagate.
        """
        if not self.cloud_login_configured:
            return False
        if self.cloud_client.logged_in:
            return True
        return await self.cloud_client.login(self._cloud_email, self._cloud_password)

    async def async_import_cloud_recipe(self, share_url_or_id: str) -> dict:
        """Fetch a recipe from an XBloom cloud share URL/id and save it locally.

        No login required — ``RecipeDetail.html`` is a public,
        unauthenticated endpoint, so this works even with no cloud account
        configured. Returns a structured ``{"success": bool, ...}`` dict
        rather than raising, so the service handler / LLM tool can surface
        a clean error either way.
        """
        local_raw = await self.cloud_client.fetch_shared_recipe(share_url_or_id)
        if local_raw is None:
            return {
                "success": False,
                "error": "fetch_failed",
                "message": (
                    "Could not fetch that recipe — check the share URL/id, "
                    "or the XBloom cloud API may be unreachable."
                ),
            }
        try:
            validated = RECIPE_SCHEMA(local_raw)
        except vol.Invalid as exc:
            return {
                "success": False,
                "error": "invalid_recipe",
                "message": f"Fetched recipe failed validation: {exc}",
            }

        entry = self.hass.config_entries.async_get_entry(self.entry_id)
        if entry is None:
            return {
                "success": False,
                "error": "entry_not_found",
                "message": "Config entry not found.",
            }

        # Name collisions get the " (2)" suffix instead of a rejection —
        # same rule as create_local_recipe, so a re-import never silently
        # overwrites local edits.
        name = dedupe_name(validated["name"], self.recipes or {})
        validated["name"] = name
        validated["uid"] = new_recipe_uid()
        validated["source"] = "import"
        # Remember where it came from so find_recipe can resolve the same
        # share URL/id back to this local copy later.
        if "://" not in share_url_or_id:
            validated.setdefault(
                "share_url",
                f"https://share-h5.xbloom.com/?id={share_url_or_id.strip()}",
            )
        else:
            validated.setdefault("share_url", share_url_or_id.strip())

        options_recipes = dict(entry.options.get(CONF_RECIPES) or {})
        options_recipes[name] = validated
        new_options = dict(entry.options)
        new_options[CONF_RECIPES] = options_recipes
        self.hass.config_entries.async_update_entry(entry, options=new_options)
        self._rebuild_recipes()
        self.async_update_listeners()
        return {
            "success": True,
            "uid": validated["uid"],
            "name": name,
            "recipe": validated,
        }

    def _rebuild_recipes(self) -> None:
        """Recompute ``self.recipes`` from both layers, lowest precedence
        first: YAML (``hass.data[DOMAIN]["yaml_recipes"]``) < the local
        store (``entry.options[CONF_RECIPES]``). A ``None`` value in the
        store is a tombstone — it hides that name from the YAML layer
        rather than being a recipe itself (used when deleting a YAML
        recipe via the UI). Mirrored by ``config_flow._all_visible_recipes``.
        Safe to call at any time; does not touch the network.
        """
        merged: Dict[str, dict] = {}
        merged.update(self.hass.data.get(DOMAIN, {}).get("yaml_recipes", {}))
        entry = self.hass.config_entries.async_get_entry(self.entry_id)
        options_recipes = (entry.options.get(CONF_RECIPES) if entry else None) or {}
        if isinstance(options_recipes, dict):
            for name, recipe in options_recipes.items():
                if recipe is None:
                    merged.pop(name, None)
                else:
                    merged[name] = recipe
        self.recipes = merged
        # _rebuild_recipes is sync (called from many non-async contexts —
        # see its own callers), but the schema refresh needs to await
        # async_get_all_descriptions, so it can't be called inline here.
        # Fire-and-forget via the event loop instead of awaiting inline.
        self.hass.async_create_task(self._async_refresh_recipe_service_schemas())

    # Services whose `recipe` field is a select selector (services.yaml
    # ships it with empty static options + custom_value: true) that we
    # keep populated with the live recipe list — see
    # _async_refresh_recipe_service_schemas.
    _RECIPE_SELECTOR_SERVICES = (
        "execute_recipe",
        "edit_recipe",
        "delete_recipe",
        "write_recipe_to_easy_slot",
        "cloud_export_recipe",
    )

    async def _async_refresh_recipe_service_schemas(self) -> None:
        """Populate the `recipe` dropdown on recipe-taking services.

        A plain text field for "which recipe" is exactly what let a typo
        (e.g. calling delete_recipe with a garbled name) fail with no
        autocomplete to catch it. services.yaml selectors can't be
        dynamic, so instead we patch the registered service schema at
        runtime via async_set_service_schema — HA re-reads it on every
        Developer Tools render. custom_value stays on, so a share URL /
        cloud id that isn't in this list yet can still be typed directly.

        Recipes are per-config-entry, but services are per-domain, so
        this merges the recipe list across every configured XBloom
        machine (deduped by uid) rather than just this coordinator's own.
        Called after every recipe-list change (see _rebuild_recipes);
        never touches the network.
        """
        merged: Dict[str, Any] = {}
        for data in self.hass.data.get(DOMAIN, {}).values():
            if not isinstance(data, dict) or DATA_COORDINATOR not in data:
                continue
            other = data[DATA_COORDINATOR]
            for name, recipe in (other.recipes or {}).items():
                uid = recipe.get("uid") or name
                merged.setdefault(uid, (name, recipe))
        options = [
            {"value": uid, "label": name}
            for uid, (name, _recipe) in sorted(merged.items(), key=lambda kv: kv[1][0].lower())
        ]

        descriptions = (await service_helper.async_get_all_descriptions(self.hass)).get(
            DOMAIN, {}
        )
        for svc_name in self._RECIPE_SELECTOR_SERVICES:
            current = descriptions.get(svc_name)
            if not current or "recipe" not in current.get("fields", {}):
                continue
            updated = copy.deepcopy(current)
            recipe_field = updated["fields"]["recipe"]
            selector = recipe_field.get("selector") or {}
            if "select" not in selector:
                continue  # not our dynamic selector (unexpected shape) — leave alone
            selector["select"]["options"] = options
            service_helper.async_set_service_schema(self.hass, DOMAIN, svc_name, updated)

    # ------------------------------------------------------------------
    # Local recipe store CRUD — the source of truth behind the recipe
    # select entity and the list/create/edit/delete services & LLM tools.
    # ------------------------------------------------------------------

    def _write_options_recipes(self, options_recipes: Dict[str, Any]) -> None:
        """Persist the store and refresh the merged view + entities."""
        entry = self.hass.config_entries.async_get_entry(self.entry_id)
        if entry is None:
            return
        new_options = dict(entry.options)
        new_options[CONF_RECIPES] = options_recipes
        self.hass.config_entries.async_update_entry(entry, options=new_options)
        self._rebuild_recipes()
        self.async_update_listeners()

    def _options_recipes(self) -> Dict[str, Any]:
        entry = self.hass.config_entries.async_get_entry(self.entry_id)
        raw = (entry.options.get(CONF_RECIPES) if entry else None) or {}
        return dict(raw) if isinstance(raw, dict) else {}

    @staticmethod
    def _looks_like_share_ref(identifier: str) -> bool:
        """Heuristic: could this unresolved identifier be a share URL/id?

        Used by edit/write-slot to decide between auto-importing and a
        plain recipe_not_found error, so a typo'd recipe name doesn't
        trigger a pointless network fetch. Share ids are base64
        (possibly percent-encoded) — recipe names practically never
        contain these characters. A bare all-digit string is also treated
        as a possible ref (a collective.xbloom.com community recipe id —
        see fetch_shared_recipe's docstring); by the time this heuristic
        runs, find_recipe has already tried it as a local cloud table id
        and failed, so this only risks one extra (cleanly-failing) network
        round-trip for the rare purely-numeric recipe name, not a wrong
        match.
        """
        s = identifier.strip()
        return "://" in s or any(c in s for c in "%=+/") or s.isdigit()

    @staticmethod
    def _summarize_local_recipe(name: str, recipe: dict) -> dict:
        summary = {
            "uid": recipe.get("uid"),
            "name": name,
            "source": recipe.get("source"),
            "dose_g": recipe.get("dose_g"),
            "ratio": recipe.get("ratio"),
            "grind_size": recipe.get("grind_size"),
            "rpm": recipe.get("rpm"),
            "cup_type": recipe.get("cup_type"),
            "pour_count": len(recipe.get("pours") or []),
        }
        if recipe.get("cloud_table_id") is not None:
            summary["cloud_table_id"] = recipe["cloud_table_id"]
        if recipe.get("share_url"):
            summary["share_url"] = recipe["share_url"]
        return summary

    def list_local_recipes(self, query: Optional[str] = None) -> dict:
        """List every local recipe (merged YAML + store view), optionally
        filtered by a case-insensitive name substring."""
        rows = [
            self._summarize_local_recipe(name, recipe)
            for name, recipe in (self.recipes or {}).items()
        ]
        if query:
            needle = query.strip().lower()
            rows = [r for r in rows if needle in (r["name"] or "").lower()]
        return {"success": True, "recipes": rows}

    def create_local_recipe(self, recipe: dict) -> dict:
        """Validate and save a new local recipe (uid assigned here).

        A name collision gets the `` (2)`` suffix rather than a rejection
        — same rule as import, so callers never silently overwrite.
        User input is never trusted for identity/cloud metadata — a
        create_recipe YAML that includes ``uid``/``cloud_table_id``/
        ``share_url``/``source`` (accidentally or otherwise) has all four
        stripped before validation; every new recipe starts as its own
        local-only identity.
        """
        try:
            validated = RECIPE_SCHEMA(strip_protected_recipe_fields(recipe))
        except vol.Invalid as exc:
            return {
                "success": False,
                "error": "invalid_recipe",
                "message": f"Recipe failed validation: {exc}",
            }
        options_recipes = self._options_recipes()
        # Dedupe against the *visible* names — a tombstoned name is free
        # to reuse (writing it just replaces the tombstone).
        name = dedupe_name(validated["name"], self.recipes or {})
        validated["name"] = name
        validated["uid"] = new_recipe_uid()
        validated["source"] = "manual"
        options_recipes[name] = validated
        self._write_options_recipes(options_recipes)
        return {"success": True, "uid": validated["uid"], "name": name}

    async def async_edit_local_recipe(self, identifier: str, changes: dict) -> dict:
        """Patch a local recipe in place (uid and cloud metadata kept).

        If ``identifier`` is a share URL/id not present locally, the
        recipe is auto-imported first (clone + uid) and the edit lands on
        the local copy — cloud recipes are never edited directly.
        """
        resolved = find_recipe(self.recipes or {}, identifier)
        if resolved is None and self._looks_like_share_ref(str(identifier)):
            imported = await self.async_import_cloud_recipe(str(identifier))
            if not imported.get("success"):
                return imported
            resolved = find_recipe(self.recipes or {}, imported["uid"])
        if resolved is None:
            return {
                "success": False,
                "error": "recipe_not_found",
                "message": f"No local recipe matches {identifier!r}.",
            }
        old_name, current = resolved

        # Identity is never patchable — it's what the edit is anchored to.
        # Stripping (rather than "restore if current already has one")
        # also blocks injecting a field current doesn't have yet, e.g.
        # a never-exported recipe's changes claiming a cloud_table_id.
        merged = {**current, **strip_protected_recipe_fields(changes or {})}
        try:
            validated = RECIPE_SCHEMA(merged)
        except vol.Invalid as exc:
            return {
                "success": False,
                "error": "invalid_recipe",
                "message": f"Edited recipe failed validation: {exc}",
            }

        options_recipes = self._options_recipes()
        new_name = validated["name"]
        if new_name != old_name and new_name in (self.recipes or {}):
            return {
                "success": False,
                "error": "name_taken",
                "message": f"A recipe named {new_name!r} already exists.",
            }
        yaml_names = set(self.hass.data.get(DOMAIN, {}).get("yaml_recipes") or {})
        if new_name != old_name:
            options_recipes.pop(old_name, None)
            if old_name in yaml_names:
                # Renaming a YAML-layer recipe must not resurface the
                # YAML original under the old name.
                options_recipes[old_name] = None
        options_recipes[new_name] = validated
        if self.selected_recipe == old_name:
            self.selected_recipe = new_name
        self._write_options_recipes(options_recipes)
        return {
            "success": True,
            "uid": validated.get("uid"),
            "name": new_name,
            "recipe": validated,
        }

    def delete_local_recipe(self, identifier: str) -> dict:
        """Delete a local recipe (the cloud copy, if any, is untouched)."""
        resolved = find_recipe(self.recipes or {}, identifier)
        if resolved is None:
            return {
                "success": False,
                "error": "recipe_not_found",
                "message": f"No local recipe matches {identifier!r}.",
            }
        name, recipe = resolved
        options_recipes = self._options_recipes()
        options_recipes.pop(name, None)
        if name in (self.hass.data.get(DOMAIN, {}).get("yaml_recipes") or {}):
            # Tombstone so the YAML layer's copy stays hidden.
            options_recipes[name] = None
        if self.selected_recipe == name:
            self.selected_recipe = None
        self._write_options_recipes(options_recipes)
        return {"success": True, "uid": recipe.get("uid"), "name": name}

    def seed_bundled_recipes(self) -> None:
        """Fresh-install fallback: write the bundled defaults as local recipes.

        Runs synchronously at setup (no network) so the recipe dropdown is
        never empty before the one-time cloud seed (a background task)
        completes. Only acts when ``entry.options[CONF_RECIPES]`` is
        empty/absent — on any later boot the store is non-empty (or the
        user deleted everything on purpose, which we respect via the
        ``CONF_RECIPES_SEEDED`` flag).
        """
        entry = self.hass.config_entries.async_get_entry(self.entry_id)
        if entry is None:
            return
        if entry.options.get(CONF_RECIPES) or entry.options.get(CONF_RECIPES_SEEDED):
            return
        seeded: Dict[str, dict] = {}
        defaults = self.hass.data.get(DOMAIN, {}).get("default_recipes") or {}
        for name, recipe in defaults.items():
            local = dict(recipe)
            local["uid"] = new_recipe_uid()
            local["source"] = "seed_bundled"
            seeded[name] = local
        if not seeded:
            return
        new_options = dict(entry.options)
        new_options[CONF_RECIPES] = seeded
        self.hass.config_entries.async_update_entry(entry, options=new_options)
        _LOGGER.info("Seeded %d bundled recipe(s) into the local store", len(seeded))

    async def async_seed_recipes(self) -> None:
        """One-time seed of the local recipe store from the cloud.

        Replaces the old always-on hourly sync layer: the local store
        (``entry.options[CONF_RECIPES]``) is the source of truth, and the
        cloud is consulted exactly once per install — the account's own
        recipes if a cloud account is configured (tracked by
        ``CONF_ACCOUNT_RECIPES_SEEDED``, so adding an account later
        triggers one more seed on the reload that follows), else XBloom's
        official public recipes (``CONF_RECIPES_SEEDED``). Fetched recipes
        become ordinary local recipes (uid + source metadata); names
        already taken locally — including tombstones (= user deletions)
        and YAML recipes — are skipped. A failed fetch leaves the flag
        unset so the next HA start retries; never raises.
        """
        entry = self.hass.config_entries.async_get_entry(self.entry_id)
        if entry is None:
            return
        account = self.cloud_login_configured
        flag = CONF_ACCOUNT_RECIPES_SEEDED if account else CONF_RECIPES_SEEDED
        if entry.options.get(flag):
            return

        fetched: Optional[list] = None
        source = ""
        if account:
            if await self.async_ensure_cloud_login():
                cloud_list = await self.cloud_client.list_recipes()
                if cloud_list is not None:
                    fetched = []
                    for raw in cloud_list:
                        local = cloud_recipe_to_local(raw)
                        # Keep the cloud identity alongside the local uid so
                        # cloud_export_recipe can update in place later.
                        if raw.get("tableId") is not None:
                            local["cloud_table_id"] = raw["tableId"]
                        if raw.get("shareRecipeLink"):
                            local["share_url"] = raw["shareRecipeLink"]
                        fetched.append(local)
                    source = "seed_cloud"
        else:
            # cup_type="Omni" only -- the collective hub's cup-type facet
            # also has a same-ish-sounding "Omni Tea Brewer" entry (its
            # actual name on the hub is "Omni Brewer"), which is the tea
            # accessory (our CupType.TEA), not a coffee cup type. Coffee
            # brewing never uses that cup type, and tea already has its
            # own curated defaults in default_recipes.py plus the
            # dedicated execute_tea_recipe path -- this seed should only
            # ever contribute coffee recipes.
            official = await self.cloud_client.fetch_official_recipes(
                limit=_OFFICIAL_RECIPE_SYNC_LIMIT, cup_type=["Omni"]
            )
            if official is not None:
                fetched = official
                source = "seed_official"

        if fetched is None:
            _LOGGER.info(
                "One-time recipe seed fetch failed (account=%s); "
                "will retry on next HA start", account,
            )
            return

        options_recipes = dict(entry.options.get(CONF_RECIPES) or {})
        yaml_names = set(self.hass.data.get(DOMAIN, {}).get("yaml_recipes") or {})
        added = 0
        for local in fetched:
            try:
                validated = RECIPE_SCHEMA(local)
            except vol.Invalid as exc:
                _LOGGER.warning(
                    "Skipping seed recipe %r: %s", local.get("name"), exc
                )
                continue
            name = validated["name"]
            # Existing local recipes, tombstones (user deletions), and
            # YAML recipes all win over the seed.
            if name in options_recipes or name in yaml_names:
                continue
            validated["uid"] = new_recipe_uid()
            validated["source"] = source
            options_recipes[name] = validated
            added += 1

        new_options = dict(entry.options)
        new_options[CONF_RECIPES] = options_recipes
        new_options[flag] = True
        if account:
            # An account seed also satisfies the initial seed — don't pull
            # official recipes on top if the account is removed later.
            new_options[CONF_RECIPES_SEEDED] = True
        self.hass.config_entries.async_update_entry(entry, options=new_options)
        self._rebuild_recipes()
        self.async_update_listeners()
        _LOGGER.info("Recipe seed complete: source=%s added=%d", source, added)

    async def async_search_collective_recipes(self, **filters) -> dict:
        """Search the public collective.xbloom.com community recipe hub.

        Unlike the private cloud-account calls (login required), this is a
        completely separate, unauthenticated API — no XBloom account
        needed at all. ``filters``
        are passed straight through to
        :meth:`_cloud_client.XBloomCloudClient.search_collective_recipes`
        (keyword/category/src/machine/cup_type/origin/varietal/process/
        roast/flavor/sort/sort_direction). Returns a structured
        ``{"success": bool, ...}`` dict rather than raising, matching the
        error-shape convention of the rest of this class.
        """
        result = await self.cloud_client.search_collective_recipes(**filters)
        if result is None:
            return {
                "success": False,
                "error": "search_failed",
                "message": "Could not search the XBloom collective recipe hub.",
            }
        return {"success": True, **result}

    async def async_export_recipe(self, identifier: str) -> dict:
        """Export a local recipe to the XBloom cloud account.

        Not logged in: no network call at all — returns just
        ``{"recipe": ...}`` (no id/link, matching the "generated locally
        only" contract). Logged in: creates the recipe on the account if
        the local copy has no ``cloud_table_id`` yet, otherwise updates
        that same cloud recipe in place (keeping id and share link
        stable), then stores the server-assigned ``cloud_table_id`` /
        ``share_url`` back on the local copy and returns
        ``{"id", "link", "recipe"}``. The share link is always the
        server's own value, never derived client-side.

        Recipes with a non-zero ``bypass_volume`` get a ``warning`` field:
        bypass-ON cloud payload requirements are still unverified live
        (see AGENTS.md) — the export proceeds anyway.
        """
        resolved = find_recipe(self.recipes or {}, identifier)
        if resolved is None:
            return {
                "success": False,
                "error": "recipe_not_found",
                "message": f"No local recipe matches {identifier!r}.",
            }
        name, raw = resolved
        warning = None
        if float(raw.get("bypass_volume") or 0) > 0:
            warning = (
                "This recipe has bypass enabled; the cloud API's bypass-ON "
                "payload requirements are unverified, so the exported copy "
                "may be rejected or altered by XBloom's servers."
            )

        if not self.cloud_login_configured:
            out: Dict[str, Any] = {"success": True, "recipe": raw}
            if warning:
                out["warning"] = warning
            return out

        try:
            validated = RECIPE_SCHEMA(dict(raw))
        except vol.Invalid as exc:
            return {
                "success": False,
                "error": "invalid_recipe",
                "message": f"Recipe does not match the schema: {exc}",
            }
        # Only enforced for bypass-off recipes — that's the formula
        # actually confirmed live (see AGENTS.md). For bypass>0 the
        # `warning` above already covers it; hard-rejecting here would
        # contradict "the export proceeds anyway" and block recipes
        # where bypass water sits on top of the dose*ratio budget
        # instead of inside it (confirmed against a live account recipe
        # 2026-07-04).
        if not warning:
            mismatch = validate_pour_volume_consistency(validated)
            if mismatch:
                return {
                    "success": False,
                    "error": "pour_volume_mismatch",
                    "message": f"Recipe rejected before sending to the cloud: {mismatch}",
                }
        if not await self.async_ensure_cloud_login():
            return {
                "success": False,
                "error": "login_failed",
                "message": (
                    "Could not log in to the XBloom cloud account — check "
                    "the configured email/password."
                ),
            }

        result: Optional[dict] = None
        table_id = raw.get("cloud_table_id")
        if table_id:
            current_raw = await self.cloud_client.get_recipe(int(table_id))
            if current_raw is None:
                # The cloud copy is gone (deleted in the app) — fall
                # through to a fresh create below.
                table_id = None
            else:
                cloud_fields = local_recipe_to_cloud(validated)
                for key in _CLOUD_EDIT_PRESERVE_KEYS:
                    if key in current_raw:
                        cloud_fields[key] = current_raw[key]
                if not await self.cloud_client.update_recipe(
                    int(table_id), cloud_fields
                ):
                    return {
                        "success": False,
                        "error": "export_failed",
                        "message": (
                            "Could not update the recipe on the XBloom "
                            "cloud account."
                        ),
                    }
                result = {
                    "table_id": int(table_id),
                    "share_url": raw.get("share_url")
                    or current_raw.get("shareRecipeLink"),
                }
        if result is None:
            created = await self.cloud_client.create_recipe(validated)
            if created is None:
                return {
                    "success": False,
                    "error": "export_failed",
                    "message": (
                        "Could not create the recipe on the XBloom cloud "
                        "account."
                    ),
                }
            result = created

        # Persist the cloud identity on the local copy so the next export
        # updates in place and find_recipe resolves the cloud id/link.
        options_recipes = self._options_recipes()
        stored = dict(options_recipes.get(name) or raw)
        stored["cloud_table_id"] = result["table_id"]
        if result.get("share_url"):
            stored["share_url"] = result["share_url"]
        options_recipes[name] = stored
        self._write_options_recipes(options_recipes)

        out = {
            "success": True,
            "id": result["table_id"],
            "link": result.get("share_url"),
            "recipe": stored,
        }
        if warning:
            out["warning"] = warning
        return out

    @property
    def recipe_names(self) -> list[str]:
        return list(self.recipes.keys()) if self.recipes else ["No recipes configured"]
