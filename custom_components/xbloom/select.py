"""Select entities for XBloom — recipe chooser, pour pattern, and mode."""
from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import (
    XBloomCoordinator,
    POUR_PATTERN_OPTIONS,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: XBloomCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    async_add_entities([
        XBloomRecipeSelect(coordinator, entry),
        XBloomPourPatternSelect(coordinator, entry),
        XBloomModeSelect(coordinator, entry),
    ])


class XBloomRecipeSelect(CoordinatorEntity[XBloomCoordinator], SelectEntity):
    _attr_translation_key = "recipe"
    _attr_unique_id = "xbloom_recipe"
    _attr_has_entity_name = True

    def __init__(self, coordinator: XBloomCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)

    @property
    def device_info(self):
        return self.coordinator.device_info

    @property
    def options(self) -> list[str]:
        return self.coordinator.recipe_names

    @property
    def current_option(self) -> str | None:
        return self.coordinator.selected_recipe

    @property
    def extra_state_attributes(self) -> dict | None:
        """Expose the selected recipe's full parameters.

        Nested under a single ``recipe`` key so it doesn't sit at the
        same level as HA-managed attributes (``friendly_name``,
        ``options``). Access via
        ``{{ state_attr('select.xbloom_recipe', 'recipe').pours }}``.
        """
        name = self.coordinator.selected_recipe
        if not name:
            return None
        recipe = (self.coordinator.recipes or {}).get(name)
        if not recipe:
            return None
        return {
            "recipe": {
                "uid": recipe.get("uid"),
                "source": recipe.get("source"),
                "cloud_table_id": recipe.get("cloud_table_id"),
                "share_url": recipe.get("share_url"),
                "name": recipe.get("name"),
                "cup_type": recipe.get("cup_type"),
                "grind_size": recipe.get("grind_size"),
                "rpm": recipe.get("rpm"),
                "dose_g": recipe.get("dose_g"),
                "ratio": recipe.get("ratio"),
                "bypass_volume": recipe.get("bypass_volume"),
                "bypass_temperature": recipe.get("bypass_temperature"),
                "pour_count": len(recipe.get("pours") or []),
                "pours": list(recipe.get("pours") or []),
            }
        }

    async def async_select_option(self, option: str) -> None:
        # select_recipe also syncs the Grind Size / RPM sliders to the
        # recipe (coffee grinding recipes only); async_update_listeners
        # inside it refreshes those number entities.
        self.coordinator.select_recipe(option)
        self.async_write_ha_state()
        _LOGGER.debug("Selected recipe: %s", option)


class XBloomPourPatternSelect(CoordinatorEntity[XBloomCoordinator], SelectEntity):
    """Pour pattern for MANUAL POUR operations.

    Note: applies only to the manual Pour button (APP_BREWER_START).
    Recipe execution uses each pour's own pattern from the recipe.

    Tracks the physical pattern knob in real time: any RD_BREWER_MODE
    (8107) notification — fired on a knob turn — is mirrored onto
    coordinator.pour_pattern by _async_update_data. Changing the select in
    HA overrides it until the next knob turn.
    """

    _attr_translation_key = "pour_pattern"
    _attr_unique_id = "xbloom_pour_pattern"
    _attr_has_entity_name = True
    _attr_options = list(POUR_PATTERN_OPTIONS.keys())  # center/circular/spiral

    def __init__(self, coordinator: XBloomCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)

    @property
    def device_info(self):
        return self.coordinator.brewer_device_info

    @property
    def current_option(self) -> str:
        for name, val in POUR_PATTERN_OPTIONS.items():
            if val == self.coordinator.pour_pattern:
                return name
        return "spiral"  # safe fallback

    async def async_select_option(self, option: str) -> None:
        self.coordinator.pour_pattern = POUR_PATTERN_OPTIONS.get(option, 2)
        self.async_write_ha_state()
        _LOGGER.debug("Pour pattern changed to: %s", option)
        # Live-adjust an armed pour screen (no-op otherwise) — the app
        # sends BREWER_SET_PATTERN (8016) live from the pour page.
        await self.coordinator.async_sync_armed_brewer_pattern()


class XBloomModeSelect(CoordinatorEntity[XBloomCoordinator], SelectEntity):
    """Machine operating mode — Pro or Easy (Auto).

    Pro Mode accepts the full 8001/8004/8002 live-brew sequence.
    Easy Mode uses the stored slot recipes activated by physical buttons.
    Recipe execution from HA automatically switches to Pro Mode first.
    """

    _attr_translation_key = "mode"
    _attr_unique_id = "xbloom_mode"
    _attr_has_entity_name = True
    _attr_options = ["pro", "easy"]

    def __init__(self, coordinator: XBloomCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)

    @property
    def device_info(self):
        return self.coordinator.device_info

    @property
    def current_option(self) -> str:
        return (self.coordinator.data or {}).get("mode", "pro")

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_mode(option)
        self.async_write_ha_state()
