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

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import (
    ATTR_BYPASS_TEMPERATURE,
    ATTR_BYPASS_VOLUME,
    ATTR_GRIND_SIZE,
    ATTR_RECIPE_NAME,
    ATTR_RPM,
    CONF_MAC_ADDRESS,
    CONF_RECIPES,
    CONF_SESSION_TIMEOUT,
    CONF_TELEMETRY_INTERVAL,
    CONF_WATER_SOURCE,
    DATA_COORDINATOR,
    DEFAULT_SESSION_TIMEOUT,
    DEFAULT_TELEMETRY_INTERVAL,
    DEFAULT_WATER_SOURCE,
    DOMAIN,
    SERVICE_EXECUTE_RECIPE,
)
from .coordinator import XBloomCoordinator, WATER_SOURCE_TANK
from .default_recipes import DEFAULT_RECIPES
from .llm_api import register_llm_api, unregister_llm_api
from .schema import POUR_SCHEMA, RECIPE_SCHEMA  # re-exported below

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.EVENT,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
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

# extra=ALLOW_EXTRA lets HA's target selector pass device_id / entity_id /
# area_id through alongside the typed fields.
EXECUTE_RECIPE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_RECIPE_NAME): cv.string,
        vol.Optional(ATTR_GRIND_SIZE): vol.All(vol.Coerce(int), vol.Range(min=1, max=80)),
        vol.Optional(ATTR_RPM): vol.All(vol.Coerce(int), vol.Range(min=60, max=120)),
        vol.Optional(ATTR_BYPASS_VOLUME): vol.All(
            vol.Coerce(float), vol.Range(min=0, max=200)
        ),
        vol.Optional(ATTR_BYPASS_TEMPERATURE): vol.All(
            vol.Coerce(float), vol.Range(min=0, max=100)
        ),
    },
    extra=vol.ALLOW_EXTRA,
)


def _coordinators_for_call(hass: HomeAssistant, call: ServiceCall) -> list:
    """Resolve which machine coordinators a service call targets.

    With no device target, applies to all configured machines (there is
    usually exactly one). With device targets, resolves each device to
    its config entry's coordinator.
    """
    all_coords = {
        eid: data[DATA_COORDINATOR]
        for eid, data in hass.data.get(DOMAIN, {}).items()
        if isinstance(data, dict) and DATA_COORDINATOR in data
    }
    device_ids = call.data.get("device_id") or []
    if not device_ids:
        return list(all_coords.values())
    dev_reg = dr.async_get(hass)
    selected = []
    for did in device_ids:
        device = dev_reg.async_get(did)
        if not device:
            continue
        for eid in device.config_entries:
            if eid in all_coords and all_coords[eid] not in selected:
                selected.append(all_coords[eid])
    return selected


def _register_services(hass: HomeAssistant) -> None:
    """Register integration services once (idempotent)."""
    if hass.services.has_service(DOMAIN, SERVICE_EXECUTE_RECIPE):
        return

    async def _handle_execute_recipe(call: ServiceCall) -> None:
        coordinators = _coordinators_for_call(hass, call)
        if not coordinators:
            raise HomeAssistantError("No XBloom machine matched the service call.")
        for coord in coordinators:
            name = call.data.get(ATTR_RECIPE_NAME) or coord.selected_recipe
            if not name or name not in (coord.recipes or {}):
                _LOGGER.warning(
                    "execute_recipe: recipe %r not found for %s",
                    name, coord.mac_address,
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
            try:
                await coord.async_execute_recipe(
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


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Load bundled defaults + YAML-defined recipes into hass.data.

    Layers (lowest precedence first), all merged into ``coordinator.recipes``
    in ``async_setup_entry``:
      1. ``default_recipes.DEFAULT_RECIPES`` — bundled with the integration.
      2. ``configuration.yaml`` ``xbloom: recipes:`` block.
      3. OptionsFlow-managed recipes in ``entry.options[CONF_RECIPES]``.
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
        hass.data[DOMAIN]["yaml_recipes"] = {r["name"]: r for r in recipes}
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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up XBloom from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    mac = entry.data[CONF_MAC_ADDRESS]
    telemetry_interval = entry.options.get(
        CONF_TELEMETRY_INTERVAL,
        entry.data.get(CONF_TELEMETRY_INTERVAL, DEFAULT_TELEMETRY_INTERVAL),
    )
    # water_source and mode are stored in options so they survive HA
    # restarts.  Falls back to sensible defaults if never set.
    initial_water_source = entry.options.get(CONF_WATER_SOURCE, DEFAULT_WATER_SOURCE)

    from .const import CONF_MODE, DEFAULT_MODE
    initial_mode = entry.options.get(CONF_MODE, DEFAULT_MODE)

    coordinator = XBloomCoordinator(
        hass=hass,
        mac_address=mac,
        entry_id=entry.entry_id,
        update_interval=telemetry_interval,
        initial_water_source=initial_water_source,
        initial_mode=initial_mode,
    )

    # Recipe merge order — lowest precedence first:
    #   1. Bundled defaults (default_recipes.DEFAULT_RECIPES)
    #   2. YAML (configuration.yaml xbloom: recipes:)
    #   3. OptionsFlow (entry.options[CONF_RECIPES])
    # Later layers override earlier ones by name so the user can always
    # shadow a default by adding a same-named YAML or UI recipe.
    merged_recipes: dict[str, dict] = {}
    merged_recipes.update(hass.data[DOMAIN].get("default_recipes", {}))
    merged_recipes.update(hass.data[DOMAIN].get("yaml_recipes", {}))
    options_recipes = entry.options.get(CONF_RECIPES) or {}
    if isinstance(options_recipes, dict):
        for name, recipe in options_recipes.items():
            if recipe is None:
                merged_recipes.pop(name, None)  # tombstone: hide from lower layers
            else:
                merged_recipes[name] = recipe
    coordinator.recipes = merged_recipes

    # Initial data fetch (non-blocking; device may not be connected yet)
    await coordinator.async_refresh()

    hass.data[DOMAIN][entry.entry_id] = {DATA_COORDINATOR: coordinator}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register the LLM API so voice/chat agents can drive the machine.
    register_llm_api(hass, entry.entry_id)

    # Register integration services (idempotent across multiple entries).
    _register_services(hass)

    # React to options changes
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change."""
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
        if not remaining and hass.services.has_service(DOMAIN, SERVICE_EXECUTE_RECIPE):
            hass.services.async_remove(DOMAIN, SERVICE_EXECUTE_RECIPE)
    return unload_ok
