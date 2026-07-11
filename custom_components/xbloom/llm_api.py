"""LLM API registration for the XBloom Coffee Machine."""
from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm

from .const import (
    DATA_COORDINATOR,
    DATA_LLM_UNREGISTER,
    DOMAIN,
    XBLOOM_LLM_API_ID,
    XBLOOM_LLM_API_NAME,
    XBLOOM_LLM_PROMPT,
)
from .coordinator import XBloomCoordinator

# Transitional (removed in T3 of tasks/2026-07-llm-platform-migration-plan.md):
# module-level catalog import keeps the old API working during the migration;
# T3 replaces it with an executor pre-import so tools load lazily.
from .llm.catalog import build_tools

_LOGGER = logging.getLogger(__name__)


class XBloomCoffeeAPI(llm.API):
    """Expose XBloom Studio control as an LLM API."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: XBloomCoordinator,
        entry_id: str,
    ) -> None:
        # Use a per-entry id so multiple machines can each register their own API.
        super().__init__(
            hass=hass,
            id=f"{XBLOOM_LLM_API_ID}_{entry_id}",
            name=f"{XBLOOM_LLM_API_NAME} ({coordinator.mac_address})",
        )
        self.coordinator = coordinator

    async def async_get_api_instance(
        self, llm_context: llm.LLMContext
    ) -> llm.APIInstance:
        tools = build_tools(self.coordinator, self.hass)
        return llm.APIInstance(
            api=self,
            api_prompt=XBLOOM_LLM_PROMPT,
            llm_context=llm_context,
            tools=tools,
        )


def register_llm_api(hass: HomeAssistant, entry_id: str) -> None:
    """Register the XBloom LLM API for a config entry."""
    entry_data = hass.data.get(DOMAIN, {}).get(entry_id)
    if not entry_data:
        _LOGGER.debug("No entry data for %s, skipping LLM API registration", entry_id)
        return
    coordinator: XBloomCoordinator = entry_data[DATA_COORDINATOR]

    api = XBloomCoffeeAPI(hass, coordinator, entry_id)
    unregister = llm.async_register_api(hass, api)
    entry_data[DATA_LLM_UNREGISTER] = unregister
    _LOGGER.info("Registered XBloom LLM API for entry %s", entry_id)


def unregister_llm_api(hass: HomeAssistant, entry_id: str) -> None:
    """Unregister the XBloom LLM API for a config entry."""
    entry_data = hass.data.get(DOMAIN, {}).get(entry_id)
    if not entry_data:
        return
    unregister = entry_data.pop(DATA_LLM_UNREGISTER, None)
    if unregister:
        try:
            unregister()
            _LOGGER.info("Unregistered XBloom LLM API for entry %s", entry_id)
        except Exception as exc:  # pragma: no cover — defensive cleanup
            _LOGGER.debug("LLM API unregister error: %s", exc)
