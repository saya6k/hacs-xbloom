"""XBloom Coffee Machine — standalone BLE integration for Home Assistant."""
from __future__ import annotations

import logging
import os
import sys

# Vendored upstream PyBloom package lives in src/xbloom/ and uses absolute
# imports (`from xbloom.X import Y`). Inject src/ onto sys.path so those
# imports resolve. Done at package init so it runs before any submodule
# (coordinator, config_flow, llm_*) is imported.
_VENDOR_PATH = os.path.join(os.path.dirname(__file__), "src")
if _VENDOR_PATH not in sys.path:
    sys.path.insert(0, _VENDOR_PATH)

import voluptuous as vol
import yaml

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import (
    ATTR_BYPASS_TEMPERATURE,
    ATTR_BYPASS_VOLUME,
    ATTR_CATEGORY,
    ATTR_CHANGES,
    ATTR_CUP_TYPE,
    ATTR_FLAVOR,
    ATTR_GRIND_SIZE,
    ATTR_KEYWORD,
    ATTR_MACHINE,
    ATTR_ORIGIN,
    ATTR_PROCESS,
    ATTR_DOSE_G,
    ATTR_QUERY,
    ATTR_RATIO,
    ATTR_RECIPE,
    ATTR_RECIPE_ID,
    ATTR_RECIPE_YAML,
    ATTR_ROAST,
    ATTR_RPM,
    ATTR_SHARE_URL,
    ATTR_SORT,
    ATTR_SORT_DIRECTION,
    ATTR_SRC,
    ATTR_VARIETAL,
    ATTR_SLOT,
    ATTR_POUR_RADIUS_LEVEL,
    ATTR_VIBRATION_AMPLITUDE_LEVEL,
    ATTR_DISPLAY_BRIGHTNESS_LEVEL,
    CONF_ACCOUNT_RECIPES_SEEDED,
    CONF_EASY_SLOTS,
    CONF_EMAIL,
    CONF_MAC_ADDRESS,
    CONF_MODE,
    CONF_PASSWORD,
    CONF_RECIPES,
    CONF_RECIPES_SEEDED,
    CONF_SESSION_TIMEOUT,
    CONF_TELEMETRY_INTERVAL,
    CONF_TEMP_UNIT,
    CONF_WATER_SOURCE,
    CONF_WEIGHT_UNIT,
    DATA_COORDINATOR,
    DEFAULT_SESSION_TIMEOUT,
    DEFAULT_TELEMETRY_INTERVAL,
    DEFAULT_TEMP_UNIT,
    DEFAULT_WATER_SOURCE,
    DEFAULT_WEIGHT_UNIT,
    DOMAIN,
    SERVICE_ADVANCED_SETTINGS,
    SERVICE_CLOUD_EXPORT_RECIPE,
    SERVICE_CLOUD_IMPORT_RECIPE,
    SERVICE_CLOUD_SEARCH_COLLECTIVE_RECIPES,
    SERVICE_CREATE_RECIPE,
    SERVICE_DELETE_RECIPE,
    SERVICE_EDIT_RECIPE,
    SERVICE_EXECUTE_RECIPE,
    SERVICE_EXECUTE_TEA_RECIPE,
    SERVICE_LIST_RECIPES,
    SERVICE_WRITE_RECIPE_TO_EASY_SLOT,
)
from .coordinator import XBloomCoordinator, WATER_SOURCE_TANK
from .default_recipes import DEFAULT_RECIPES
from .llm_api import register_llm_api, unregister_llm_api
from .schema import (  # POUR_SCHEMA/RECIPE_SCHEMA re-exported below
    POUR_SCHEMA,
    RECIPE_SCHEMA,
    find_recipe,
    new_recipe_uid,
    yaml_recipe_uid,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.EVENT,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.UPDATE,
]

# YAML / options recipe schemas live in ``schema.py`` so the OptionsFlow
# can import them without a circular dependency on this module. Names
# re-exported above (``POUR_SCHEMA`` / ``RECIPE_SCHEMA``) for compatibility
# with anything that previously imported from ``custom_components.xbloom``.

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional(CONF_RECIPES, default=[]): [RECIPE_SCHEMA],
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

# extra=ALLOW_EXTRA lets config_entry_id (a custom field, not HA's
# built-in target: mechanism — see _coordinators_for_call) pass through
# alongside the typed fields below without being explicitly declared in
# every one of these schemas.
EXECUTE_RECIPE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_RECIPE): cv.string,
        vol.Optional(ATTR_GRIND_SIZE): vol.All(vol.Coerce(int), vol.Range(min=1, max=80)),
        vol.Optional(ATTR_RPM): vol.All(vol.Coerce(int), vol.Range(min=60, max=120)),
        vol.Optional(ATTR_DOSE_G): vol.All(
            vol.Coerce(float), vol.Range(min=1, max=100)
        ),
        vol.Optional(ATTR_RATIO): vol.All(
            vol.Coerce(float), vol.Range(min=1, max=50)
        ),
        vol.Optional(ATTR_CUP_TYPE): vol.In(
            ["x_pod", "xpod", "omni_dripper", "other", "tea"]
        ),
        vol.Optional(ATTR_BYPASS_VOLUME): vol.All(
            vol.Coerce(float), vol.Range(min=0, max=200)
        ),
        vol.Optional(ATTR_BYPASS_TEMPERATURE): vol.All(
            vol.Coerce(float), vol.Range(min=0, max=100)
        ),
    },
    extra=vol.ALLOW_EXTRA,
)

# No dose/ratio/grind/bypass — none apply to the tea BLE sequence.
EXECUTE_TEA_RECIPE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_RECIPE): cv.string,
    },
    extra=vol.ALLOW_EXTRA,
)

CLOUD_IMPORT_RECIPE_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Optional(ATTR_SHARE_URL): cv.string,
            vol.Optional(ATTR_RECIPE_ID): cv.string,
        },
        extra=vol.ALLOW_EXTRA,
    ),
    cv.has_at_least_one_key(ATTR_SHARE_URL, ATTR_RECIPE_ID),
)

LIST_RECIPES_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_QUERY): cv.string,
    },
    extra=vol.ALLOW_EXTRA,
)

CREATE_RECIPE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_RECIPE_YAML): cv.string,
    },
    extra=vol.ALLOW_EXTRA,
)

EDIT_RECIPE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_RECIPE): cv.string,
        vol.Required(ATTR_CHANGES): cv.string,
    },
    extra=vol.ALLOW_EXTRA,
)

DELETE_RECIPE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_RECIPE): cv.string,
    },
    extra=vol.ALLOW_EXTRA,
)

CLOUD_EXPORT_RECIPE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_RECIPE): cv.string,
    },
    extra=vol.ALLOW_EXTRA,
)

WRITE_RECIPE_TO_EASY_SLOT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_SLOT): vol.All(cv.string, vol.Upper, vol.In(["A", "B", "C"])),
        vol.Optional(ATTR_RECIPE): cv.string,
    },
    extra=vol.ALLOW_EXTRA,
)

ADVANCED_SETTINGS_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_POUR_RADIUS_LEVEL): vol.All(vol.Coerce(int), vol.Range(min=0, max=4)),
        vol.Optional(ATTR_VIBRATION_AMPLITUDE_LEVEL): vol.All(vol.Coerce(int), vol.Range(min=0, max=5)),
        vol.Optional(ATTR_DISPLAY_BRIGHTNESS_LEVEL): vol.All(vol.Coerce(int), vol.Range(min=1, max=3)),
    },
    extra=vol.ALLOW_EXTRA,
)


# Facet filters are lists of codes and/or display names — the services.yaml
# multi-select submits snapshot codes (custom values allowed for categories
# added upstream later), the LLM tool passes name lists; both are resolved
# against the live criteria table in _cloud_client._resolve_criteria_values.
_FACET_LIST = vol.All(cv.ensure_list, [cv.string])

CLOUD_SEARCH_COLLECTIVE_RECIPES_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_KEYWORD): cv.string,
        vol.Optional(ATTR_CATEGORY): vol.In(["coffee", "tea"]),
        vol.Optional(ATTR_SRC): vol.In(["official", "user"]),
        vol.Optional(ATTR_MACHINE): _FACET_LIST,
        vol.Optional(ATTR_CUP_TYPE): _FACET_LIST,
        vol.Optional(ATTR_ORIGIN): _FACET_LIST,
        vol.Optional(ATTR_VARIETAL): _FACET_LIST,
        vol.Optional(ATTR_PROCESS): _FACET_LIST,
        vol.Optional(ATTR_ROAST): _FACET_LIST,
        vol.Optional(ATTR_FLAVOR): _FACET_LIST,
        vol.Optional(ATTR_SORT, default="likes"): vol.In(["date", "likes", "downloads"]),
        vol.Optional(ATTR_SORT_DIRECTION, default="desc"): vol.In(["asc", "desc"]),
    },
    extra=vol.ALLOW_EXTRA,
)



def _coordinators_for_call(hass: HomeAssistant, call: ServiceCall) -> list:
    """Resolve which machine coordinators a service call targets.

    With no config_entry target, applies to all configured machines
    (there is usually exactly one). A ``config_entry`` selector (not
    ``device``) is used so the picker offers exactly one item per
    physical XBloom machine — a device selector would also list the
    Grinder/Scale/Brewer child devices (see the device-registry section
    in AGENTS.md), and there's no way to filter those out of a plain
    fields-level device selector (hassfest rejects an ``entity:`` filter
    key there; that's only valid inside a ``target:`` block, which these
    services don't use). Each config entry maps 1:1 to a coordinator
    already, so no device-registry lookup is needed at all.

    ``config_entry_id`` is a bare string, not a list — HA's
    ``ConfigEntrySelector`` has no ``multiple`` option (confirmed against
    core's own ``helpers/selector.py``, see AGENTS.md), so a real call
    only ever carries at most one id. Hardware-reported 2026-07-17: this
    used to do ``for eid in entry_ids`` over that string, which iterates
    it character-by-character — no single character ever matches a real
    config entry id, so every service call that actually specified a
    target machine failed with "No XBloom machine matched the service
    call," regardless of which service.
    """
    all_coords = {
        eid: data[DATA_COORDINATOR]
        for eid, data in hass.data.get(DOMAIN, {}).items()
        if isinstance(data, dict) and DATA_COORDINATOR in data
    }
    entry_id = call.data.get("config_entry_id")
    if not entry_id:
        return list(all_coords.values())
    coordinator = all_coords.get(entry_id)
    return [coordinator] if coordinator else []


def _register_services(hass: HomeAssistant) -> None:
    """Register integration services once (idempotent)."""
    if hass.services.has_service(DOMAIN, SERVICE_EXECUTE_RECIPE):
        return

    async def _handle_execute_recipe(call: ServiceCall) -> None:
        coordinators = _coordinators_for_call(hass, call)
        if not coordinators:
            raise HomeAssistantError("No XBloom machine matched the service call.")
        for coord in coordinators:
            identifier = call.data.get(ATTR_RECIPE)
            if identifier:
                resolved = find_recipe(coord.recipes or {}, identifier)
                name = resolved[0] if resolved else None
            else:
                name = coord.selected_recipe
            if not name or name not in (coord.recipes or {}):
                _LOGGER.warning(
                    "execute_recipe: recipe %r not found for %s",
                    identifier or name, coord.mac_address,
                )
                continue
            # select_recipe syncs the grind/RPM sliders to the recipe;
            # explicit overrides then take precedence for this brew.
            coord.select_recipe(name)
            if ATTR_GRIND_SIZE in call.data:
                coord.grind_size = int(call.data[ATTR_GRIND_SIZE])
            if ATTR_RPM in call.data:
                coord.rpm = int(call.data[ATTR_RPM])
            coord.async_update_listeners()
            overrides = {
                key: call.data[key]
                for key in (ATTR_DOSE_G, ATTR_RATIO, ATTR_CUP_TYPE)
                if key in call.data
            }
            try:
                await coord.async_execute_recipe(
                    overrides=overrides or None,
                    bypass_volume=call.data.get(ATTR_BYPASS_VOLUME),
                    bypass_temperature=call.data.get(ATTR_BYPASS_TEMPERATURE),
                )
            except HomeAssistantError as exc:
                # e.g. low water — don't let one machine's pre-brew check
                # abort the recipe for the rest of the targeted machines.
                _LOGGER.warning(
                    "execute_recipe skipped for %s: %s", coord.mac_address, exc,
                )

    hass.services.async_register(
        DOMAIN,
        SERVICE_EXECUTE_RECIPE,
        _handle_execute_recipe,
        schema=EXECUTE_RECIPE_SCHEMA,
    )

    async def _handle_execute_tea_recipe(call: ServiceCall) -> None:
        """Leaner sibling of execute_recipe for tea — see brewing.py's
        _async_brew_tea, which takes no dose/ratio/grind/bypass overrides."""
        coordinators = _coordinators_for_call(hass, call)
        if not coordinators:
            raise HomeAssistantError("No XBloom machine matched the service call.")
        for coord in coordinators:
            identifier = call.data.get(ATTR_RECIPE)
            if identifier:
                resolved = find_recipe(coord.recipes or {}, identifier)
                name = resolved[0] if resolved else None
            else:
                name = coord.selected_recipe
            if not name or name not in (coord.recipes or {}):
                _LOGGER.warning(
                    "execute_tea_recipe: recipe %r not found for %s",
                    identifier or name, coord.mac_address,
                )
                continue
            recipe = coord.recipes[name]
            if str(recipe.get("cup_type", "")).strip().lower() != "tea":
                _LOGGER.warning(
                    "execute_tea_recipe: %r is not a tea recipe (cup_type=%r) — "
                    "use execute_recipe instead. Skipped for %s.",
                    name, recipe.get("cup_type"), coord.mac_address,
                )
                continue
            coord.select_recipe(name)
            try:
                await coord.async_execute_recipe()
            except HomeAssistantError as exc:
                _LOGGER.warning(
                    "execute_tea_recipe skipped for %s: %s", coord.mac_address, exc,
                )

    hass.services.async_register(
        DOMAIN,
        SERVICE_EXECUTE_TEA_RECIPE,
        _handle_execute_tea_recipe,
        schema=EXECUTE_TEA_RECIPE_SCHEMA,
    )

    async def _handle_cloud_import_recipe(call: ServiceCall) -> ServiceResponse:
        coordinators = _coordinators_for_call(hass, call)
        if not coordinators:
            raise HomeAssistantError("No XBloom machine matched the service call.")
        identifier = call.data.get(ATTR_SHARE_URL) or call.data.get(ATTR_RECIPE_ID)
        # Imports into every targeted machine's local store; the response
        # reflects the first machine (there is usually exactly one).
        first: ServiceResponse = None
        for coord in coordinators:
            result = await coord.async_import_cloud_recipe(identifier)
            if not result.get("success"):
                _LOGGER.warning(
                    "cloud_import_recipe failed for %s: %s",
                    coord.mac_address, result.get("message", result.get("error")),
                )
                continue
            if first is None:
                first = {
                    "uid": result["uid"],
                    "name": result["name"],
                    "recipe": result["recipe"],
                }
        if first is None:
            raise HomeAssistantError("cloud_import_recipe failed on every machine.")
        return first

    hass.services.async_register(
        DOMAIN,
        SERVICE_CLOUD_IMPORT_RECIPE,
        _handle_cloud_import_recipe,
        schema=CLOUD_IMPORT_RECIPE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def _handle_write_recipe_to_easy_slot(call: ServiceCall) -> ServiceResponse:
        coordinators = _coordinators_for_call(hass, call)
        if not coordinators:
            raise HomeAssistantError("No XBloom machine matched the service call.")
        result = await coordinators[0].async_write_easy_slot(
            call.data[ATTR_SLOT], identifier=call.data.get(ATTR_RECIPE)
        )
        if not result.get("success"):
            raise HomeAssistantError(
                result.get("message", "write_recipe_to_easy_slot failed")
            )
        return {"slot": result["slot"], "uid": result["uid"], "name": result["name"]}

    hass.services.async_register(
        DOMAIN,
        SERVICE_WRITE_RECIPE_TO_EASY_SLOT,
        _handle_write_recipe_to_easy_slot,
        schema=WRITE_RECIPE_TO_EASY_SLOT_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def _handle_advanced_settings(call: ServiceCall) -> ServiceResponse:
        coordinators = _coordinators_for_call(hass, call)
        if not coordinators:
            raise HomeAssistantError("No XBloom machine matched the service call.")
        result = await coordinators[0].async_set_advanced_settings(
            pour_radius_level=call.data.get(ATTR_POUR_RADIUS_LEVEL),
            vibration_amplitude_level=call.data.get(ATTR_VIBRATION_AMPLITUDE_LEVEL),
            display_brightness_level=call.data.get(ATTR_DISPLAY_BRIGHTNESS_LEVEL),
        )
        if not result.get("success"):
            raise HomeAssistantError(result.get("message", "advanced_settings failed"))
        return result

    hass.services.async_register(
        DOMAIN,
        SERVICE_ADVANCED_SETTINGS,
        _handle_advanced_settings,
        schema=ADVANCED_SETTINGS_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def _handle_cloud_export_recipe(call: ServiceCall) -> ServiceResponse:
        coordinators = _coordinators_for_call(hass, call)
        if not coordinators:
            raise HomeAssistantError("No XBloom machine matched the service call.")
        # Cloud accounts are per-machine credentials — export from the
        # first targeted machine's store/account.
        result = await coordinators[0].async_export_recipe(call.data[ATTR_RECIPE])
        if not result.get("success"):
            raise HomeAssistantError(result.get("message", "cloud_export_recipe failed"))
        response: ServiceResponse = {"recipe": result["recipe"]}
        if "id" in result:
            response["id"] = result["id"]
            response["link"] = result.get("link")
        if result.get("warning"):
            response["warning"] = result["warning"]
        return response

    hass.services.async_register(
        DOMAIN,
        SERVICE_CLOUD_EXPORT_RECIPE,
        _handle_cloud_export_recipe,
        schema=CLOUD_EXPORT_RECIPE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    # The local recipe store is per machine (per config entry) — like the
    # cloud-account services before them, the local CRUD services act on
    # the first targeted machine's store (there is usually exactly one).

    async def _handle_list_recipes(call: ServiceCall) -> ServiceResponse:
        coordinators = _coordinators_for_call(hass, call)
        if not coordinators:
            raise HomeAssistantError("No XBloom machine matched the service call.")
        result = coordinators[0].list_local_recipes(query=call.data.get(ATTR_QUERY))
        return {"recipes": result["recipes"]}

    hass.services.async_register(
        DOMAIN,
        SERVICE_LIST_RECIPES,
        _handle_list_recipes,
        schema=LIST_RECIPES_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    def _parse_yaml_mapping(text: str) -> dict:
        try:
            parsed = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise HomeAssistantError(f"Invalid recipe YAML: {exc}") from exc
        if not isinstance(parsed, dict):
            raise HomeAssistantError("Recipe YAML must be a mapping.")
        return parsed

    async def _handle_create_recipe(call: ServiceCall) -> ServiceResponse:
        coordinators = _coordinators_for_call(hass, call)
        if not coordinators:
            raise HomeAssistantError("No XBloom machine matched the service call.")
        parsed = _parse_yaml_mapping(call.data[ATTR_RECIPE_YAML])
        result = coordinators[0].create_local_recipe(parsed)
        if not result.get("success"):
            raise HomeAssistantError(result.get("message", "create_recipe failed"))
        return {"uid": result["uid"], "name": result["name"]}

    hass.services.async_register(
        DOMAIN,
        SERVICE_CREATE_RECIPE,
        _handle_create_recipe,
        schema=CREATE_RECIPE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def _handle_edit_recipe(call: ServiceCall) -> ServiceResponse:
        coordinators = _coordinators_for_call(hass, call)
        if not coordinators:
            raise HomeAssistantError("No XBloom machine matched the service call.")
        # Partial by design — only the fields present in `changes` move;
        # everything else (including uid/cloud metadata) stays.
        changes = _parse_yaml_mapping(call.data[ATTR_CHANGES])
        result = await coordinators[0].async_edit_local_recipe(
            call.data[ATTR_RECIPE], changes
        )
        if not result.get("success"):
            raise HomeAssistantError(result.get("message", "edit_recipe failed"))
        return {"uid": result["uid"], "name": result["name"], "recipe": result["recipe"]}

    hass.services.async_register(
        DOMAIN,
        SERVICE_EDIT_RECIPE,
        _handle_edit_recipe,
        schema=EDIT_RECIPE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def _handle_delete_recipe(call: ServiceCall) -> ServiceResponse:
        coordinators = _coordinators_for_call(hass, call)
        if not coordinators:
            raise HomeAssistantError("No XBloom machine matched the service call.")
        result = coordinators[0].delete_local_recipe(call.data[ATTR_RECIPE])
        if not result.get("success"):
            raise HomeAssistantError(result.get("message", "delete_recipe failed"))
        return {"uid": result["uid"], "name": result["name"]}

    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_RECIPE,
        _handle_delete_recipe,
        schema=DELETE_RECIPE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def _handle_cloud_search_collective_recipes(call: ServiceCall) -> ServiceResponse:
        coordinators = _coordinators_for_call(hass, call)
        if not coordinators:
            raise HomeAssistantError("No XBloom machine matched the service call.")
        # Public, unauthenticated, and not tied to any one machine's cloud
        # account — reuses the first targeted machine's coordinator purely
        # for its HTTP session / cached criteria lookup, same device
        # resolution convention as cloud_search_recipes.
        result = await coordinators[0].async_search_collective_recipes(
            keyword=call.data.get(ATTR_KEYWORD),
            category=call.data.get(ATTR_CATEGORY),
            src=call.data.get(ATTR_SRC),
            machine=call.data.get(ATTR_MACHINE),
            cup_type=call.data.get(ATTR_CUP_TYPE),
            origin=call.data.get(ATTR_ORIGIN),
            varietal=call.data.get(ATTR_VARIETAL),
            process=call.data.get(ATTR_PROCESS),
            roast=call.data.get(ATTR_ROAST),
            flavor=call.data.get(ATTR_FLAVOR),
            sort=call.data.get(ATTR_SORT, "likes"),
            sort_direction=call.data.get(ATTR_SORT_DIRECTION, "desc"),
        )
        if not result.get("success"):
            raise HomeAssistantError(
                result.get("message", "cloud_search_collective_recipes failed")
            )
        return {
            "recipes": result["list"],
            "total": result.get("total"),
            "unmatched": result.get("unmatched"),
        }

    hass.services.async_register(
        DOMAIN,
        SERVICE_CLOUD_SEARCH_COLLECTIVE_RECIPES,
        _handle_cloud_search_collective_recipes,
        schema=CLOUD_SEARCH_COLLECTIVE_RECIPES_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )



async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Load bundled defaults + YAML-defined recipes into hass.data.

    ``hass.data[DOMAIN]["default_recipes"]`` (``default_recipes.DEFAULT_RECIPES``)
    is only used by ``coordinator.seed_bundled_recipes()`` — the fresh-install
    seed that fills the local store before the one-time cloud seed
    (``coordinator.async_seed_recipes``) completes. Recipe merge order
    (lowest precedence first), rebuilt by ``coordinator._rebuild_recipes()``:
      1. ``configuration.yaml`` ``xbloom: recipes:`` block.
      2. The local store — ``entry.options[CONF_RECIPES]`` (source of truth).
    """
    hass.data.setdefault(DOMAIN, {})

    # Defaults are validated through the same schema as YAML so any
    # malformed default is caught at startup rather than at brew time.
    validated_defaults: dict[str, dict] = {}
    for raw in DEFAULT_RECIPES:
        try:
            validated = RECIPE_SCHEMA(raw)
        except vol.Invalid as exc:
            _LOGGER.error(
                "Bundled default recipe %r failed schema validation; skipping: %s",
                raw.get("name", "<unnamed>"), exc,
            )
            continue
        validated_defaults[validated["name"]] = validated
    hass.data[DOMAIN]["default_recipes"] = validated_defaults

    if DOMAIN in config and CONF_RECIPES in config[DOMAIN]:
        recipes = config[DOMAIN][CONF_RECIPES]
        # YAML recipes are re-loaded every boot, so their uid must be
        # deterministic (derived from the name) to stay stable.
        hass.data[DOMAIN]["yaml_recipes"] = {
            r["name"]: {**r, "uid": yaml_recipe_uid(r["name"]), "source": "yaml"}
            for r in recipes
        }
        _LOGGER.info(
            "Loaded %d default + %d YAML recipe(s)",
            len(validated_defaults), len(recipes),
        )
    else:
        hass.data[DOMAIN]["yaml_recipes"] = {}
        _LOGGER.info(
            "Loaded %d default recipe(s); no YAML recipes configured",
            len(validated_defaults),
        )

    return True


def _migrate_recipe_v1_to_v2(recipe: dict) -> dict:
    """Translate one v1-schema recipe dict to the v2 (cloud-shaped) schema.

    v1: bean_weight/total_water, pours[].volume/temperature/pausing.
    v2: dose_g/ratio, pours[].volume_ml/temperature_c/pause_seconds.
    ``pattern``/``vibration`` are unchanged — only the renamed fields move.
    """
    dose_g = float(recipe.get("bean_weight", 15.0))
    total_water = float(recipe.get("total_water", 250))
    # ratio is meaningless for a zero dose (tea) — omit it and let
    # schema.compute_total_water_ml's pour-volume-sum fallback take over,
    # exactly as it did pre-migration when total_water was stored directly.
    ratio = (total_water / dose_g) if dose_g > 0 else None

    new_pours = []
    for p in recipe.get("pours", []):
        new_pour = dict(p)
        if "volume" in new_pour:
            new_pour["volume_ml"] = new_pour.pop("volume")
        if "temperature" in new_pour:
            new_pour["temperature_c"] = new_pour.pop("temperature")
        if "pausing" in new_pour:
            new_pour["pause_seconds"] = new_pour.pop("pausing")
        new_pours.append(new_pour)

    new_recipe = dict(recipe)
    new_recipe.pop("bean_weight", None)
    new_recipe.pop("total_water", None)
    new_recipe["dose_g"] = dose_g
    new_recipe["ratio"] = ratio
    new_recipe["pours"] = new_pours
    return new_recipe


def _migrate_recipe_v2_to_v3(recipe: dict) -> dict:
    """Inject the v3 local-store metadata into one v2 recipe dict.

    Every stored recipe gains a ``uid`` (the stable local identity) and a
    ``source`` of ``manual`` — v2 predates seed provenance, and options
    recipes were by definition user-managed. Existing metadata (e.g. a
    dict that somehow already has a uid) is left untouched.
    """
    migrated = dict(recipe)
    migrated.setdefault("uid", new_recipe_uid())
    migrated.setdefault("source", "manual")
    return migrated


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate a config entry to the current schema version.

    v1 -> v2: recipes stored in ``entry.options[CONF_RECIPES]`` are
    rewritten from the old field names to the cloud-shaped ones (see
    ``_migrate_recipe_v1_to_v2``). Recipes defined in ``configuration.yaml``
    are NOT touched here — the integration doesn't own that file — so YAML
    users must update their field names by hand; this logs a pointer to do so.

    v2 -> v3: every stored recipe gains local-store metadata (``uid`` /
    ``source`` — see ``_migrate_recipe_v2_to_v3``); tombstones (None) are
    preserved as-is.
    """
    if entry.version == 1:
        options_recipes = entry.options.get(CONF_RECIPES) or {}
        if isinstance(options_recipes, dict) and options_recipes:
            migrated = {
                name: (_migrate_recipe_v1_to_v2(recipe) if recipe is not None else None)
                for name, recipe in options_recipes.items()
            }
            new_options = dict(entry.options)
            new_options[CONF_RECIPES] = migrated
            hass.config_entries.async_update_entry(
                entry, options=new_options, version=2,
            )
            _LOGGER.info(
                "Migrated %d UI-managed recipe(s) to the new schema "
                "(dose_g/ratio, pours[].volume_ml/temperature_c/pause_seconds)",
                len([r for r in migrated.values() if r is not None]),
            )
        else:
            hass.config_entries.async_update_entry(entry, version=2)

        _LOGGER.warning(
            "XBloom recipe schema changed (bean_weight/total_water -> "
            "dose_g/ratio; pours[].volume/temperature/pausing -> "
            "volume_ml/temperature_c/pause_seconds). UI-managed recipes "
            "were migrated automatically. If you define recipes in "
            "configuration.yaml, update their field names by hand — see "
            "the README for the new recipe format."
        )

    if entry.version == 2:
        options_recipes = entry.options.get(CONF_RECIPES) or {}
        if isinstance(options_recipes, dict) and options_recipes:
            migrated = {
                name: (_migrate_recipe_v2_to_v3(recipe) if recipe is not None else None)
                for name, recipe in options_recipes.items()
            }
            new_options = dict(entry.options)
            new_options[CONF_RECIPES] = migrated
            hass.config_entries.async_update_entry(
                entry, options=new_options, version=3,
            )
            _LOGGER.info(
                "Migrated %d UI-managed recipe(s) to v3 (local uid/source metadata)",
                len([r for r in migrated.values() if r is not None]),
            )
        else:
            hass.config_entries.async_update_entry(entry, version=3)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up XBloom from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    mac = entry.data[CONF_MAC_ADDRESS]
    telemetry_interval = entry.options.get(
        CONF_TELEMETRY_INTERVAL,
        entry.data.get(CONF_TELEMETRY_INTERVAL, DEFAULT_TELEMETRY_INTERVAL),
    )
    # water_source, mode, and the display units are stored in options so
    # they survive HA restarts.  Falls back to sensible defaults if never set.
    initial_water_source = entry.options.get(CONF_WATER_SOURCE, DEFAULT_WATER_SOURCE)

    from .const import DEFAULT_MODE
    initial_mode = entry.options.get(CONF_MODE, DEFAULT_MODE)
    initial_weight_unit = entry.options.get(CONF_WEIGHT_UNIT, DEFAULT_WEIGHT_UNIT)
    initial_temp_unit = entry.options.get(CONF_TEMP_UNIT, DEFAULT_TEMP_UNIT)

    coordinator = XBloomCoordinator(
        hass=hass,
        mac_address=mac,
        entry_id=entry.entry_id,
        update_interval=telemetry_interval,
        initial_water_source=initial_water_source,
        initial_mode=initial_mode,
        initial_weight_unit=initial_weight_unit,
        initial_temp_unit=initial_temp_unit,
        cloud_email=entry.data.get(CONF_EMAIL),
        cloud_password=entry.data.get(CONF_PASSWORD),
    )

    # Recipe merge order — lowest precedence first:
    #   1. YAML (configuration.yaml xbloom: recipes:)
    #   2. The local store (entry.options[CONF_RECIPES]) — source of truth.
    # On a fresh install the store is empty, so seed it synchronously with
    # the bundled default_recipes.py list (no network) — the one-time
    # cloud seed (a background task, kicked off below) adds the account's
    # own or XBloom's official recipes on top.
    coordinator.seed_bundled_recipes()
    coordinator._rebuild_recipes()

    # Initial data fetch (non-blocking; device may not be connected yet)
    await coordinator.async_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        DATA_COORDINATOR: coordinator,
        # Snapshot for _async_update_listener's recipe-only-change check.
        "options_snapshot": dict(entry.options),
    }
    # coordinator.seed_bundled_recipes() + _rebuild_recipes() above ran
    # before this entry was registered in hass.data, so the recipe-service
    # dropdown refresh they triggered couldn't see this machine's own
    # recipes yet (only any other already-configured machine's). Refresh
    # once more now that self-lookup works.
    await coordinator._async_refresh_recipe_service_schemas()

    # Register the main device explicitly, before any platform is set up.
    # async_forward_entry_setups fans the platforms out concurrently, so
    # relying on whichever entity happens to reference the main device
    # first is a race: if a platform whose entities all point at a
    # sub-device (grinder/scale/brewer, via_device=(DOMAIN, entry.entry_id))
    # registers before any main-device entity does, HA logs "non existing
    # via_device" (confirmed live 2026-07-15, binary_sensor.py). Explicit
    # registration here removes the ordering dependency entirely.
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name="XBloom Coffee Machine",
        manufacturer="XBloom",
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register the LLM API so voice/chat agents can drive the machine.
    register_llm_api(hass, entry.entry_id)

    # Register integration services (idempotent across multiple entries).
    _register_services(hass)

    # React to options changes
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # One-time cloud seed of the local recipe store (account recipes if an
    # account is configured, else XBloom's official public recipes) — run
    # in the background so a slow/unreachable cloud API can't delay
    # integration setup. No-ops once the seed flags are set; there is no
    # periodic re-sync anymore (the local store is the source of truth).
    hass.async_create_task(coordinator.async_seed_recipes())

    return True


# Options keys that only affect the recipe store — writes touching nothing
# else (seed task, import/create/edit/delete services) must not bounce the
# BLE connection with a full reload; a recipe rebuild is enough.
_RECIPE_ONLY_OPTION_KEYS = {
    CONF_RECIPES,
    CONF_RECIPES_SEEDED,
    CONF_ACCOUNT_RECIPES_SEEDED,
    CONF_EASY_SLOTS,
}

# CONF_MODE is persisted by XBloomCoordinator.async_set_mode() purely so the
# preference survives restarts/reconnects — the BLE mode-switch command has
# already been sent over the air by that point. Live-observed 2026-07-04: a
# full reload here disconnects BLE (async_unload_entry -> async_disconnect())
# and nothing reconnects automatically afterwards, so the connection switch
# was left stuck "off" on every mode change. No BLE-affecting work is needed
# for this key, so it's exempt from the reload just like the recipe keys.
# The unit/water-source keys are exempt for the same reason (they used to
# reload — and therefore drop the BLE connection — on every water-source
# select change); their only follow-up is pushing the new values to the
# machine, which coordinator._handle_unit_options_change() does in place.
_UNIT_OPTION_KEYS = {CONF_WATER_SOURCE, CONF_WEIGHT_UNIT, CONF_TEMP_UNIT}
_NO_RELOAD_OPTION_KEYS = _RECIPE_ONLY_OPTION_KEYS | {CONF_MODE} | _UNIT_OPTION_KEYS


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change.

    Exception: changes confined to ``_NO_RELOAD_OPTION_KEYS`` (the recipe
    store, the mode preference, and the unit/water-source preferences)
    skip the reload — a recipe rebuild / an in-place unit push is enough —
    so these updates apply without dropping the BLE connection.
    """
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if data and DATA_COORDINATOR in data:
        prev = data.get("options_snapshot") or {}
        cur = dict(entry.options)
        changed = {k for k in set(prev) | set(cur) if prev.get(k) != cur.get(k)}
        data["options_snapshot"] = cur
        if changed and changed <= _NO_RELOAD_OPTION_KEYS:
            coordinator: XBloomCoordinator = data[DATA_COORDINATOR]
            if changed & _RECIPE_ONLY_OPTION_KEYS:
                coordinator._rebuild_recipes()
            if changed & _UNIT_OPTION_KEYS:
                coordinator._handle_unit_options_change(cur)
            coordinator.async_update_listeners()
            return
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry and disconnect BLE."""
    unregister_llm_api(hass, entry.entry_id)

    coordinator: XBloomCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    await coordinator.async_disconnect()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        # Drop the service once the last machine is gone.
        remaining = [
            data for data in hass.data.get(DOMAIN, {}).values()
            if isinstance(data, dict) and DATA_COORDINATOR in data
        ]
        if not remaining:
            for service in (
                SERVICE_EXECUTE_RECIPE,
                SERVICE_EXECUTE_TEA_RECIPE,
                SERVICE_LIST_RECIPES,
                SERVICE_CREATE_RECIPE,
                SERVICE_EDIT_RECIPE,
                SERVICE_DELETE_RECIPE,
                SERVICE_CLOUD_IMPORT_RECIPE,
                SERVICE_CLOUD_EXPORT_RECIPE,
                SERVICE_CLOUD_SEARCH_COLLECTIVE_RECIPES,
                SERVICE_WRITE_RECIPE_TO_EASY_SLOT,
                SERVICE_ADVANCED_SETTINGS,
            ):
                if hass.services.has_service(DOMAIN, service):
                    hass.services.async_remove(DOMAIN, service)
        else:
            # Drop this machine's recipes from the other machines'
            # recipe-service dropdowns (see
            # _async_refresh_recipe_service_schemas).
            await remaining[0][DATA_COORDINATOR]._async_refresh_recipe_service_schemas()
    return unload_ok
