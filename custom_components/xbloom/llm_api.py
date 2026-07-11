"""LLM API registration for the XBloom Coffee Machine.

Thin shell around the llm/ platform package: the per-entry custom API that
users opt into from their conversation-agent settings. Tool building lives
in llm/catalog.py, reached through the platform's async_get_tools callback.

This module must never import the llm/ package (or any submodule — a
submodule import executes the package __init__ first) at module level:
the setup path imports this file, and pulling llm/ in would defeat the
platform's lazy loading. The platform is referenced by string module path
and pre-imported in the executor on first use instead.
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm
from homeassistant.helpers.importlib import async_import_module

from .const import (
    CONF_MAC_ADDRESS,
    DOMAIN,
    XBLOOM_LLM_API_ID,
    XBLOOM_LLM_API_NAME,
)

_LOGGER = logging.getLogger(__name__)

_PLATFORM = f"custom_components.{DOMAIN}.llm"


class XBloomCoffeeAPI(llm.API):
    """Expose XBloom Studio control as an LLM API."""

    def __init__(self, hass: HomeAssistant, entry_id: str, mac_address: str) -> None:
        # Use a per-entry id so multiple machines can each register their own API.
        super().__init__(
            hass=hass,
            id=f"{XBLOOM_LLM_API_ID}_{entry_id}",
            name=f"{XBLOOM_LLM_API_NAME} ({mac_address})",
        )

    async def async_get_api_instance(
        self, llm_context: llm.LLMContext
    ) -> llm.APIInstance:
        # Pre-import in the executor so the platform callback's function-level
        # imports are cache hits — HA's block_async_io flags a module's first
        # import inside the event loop.
        await async_import_module(self.hass, f"{_PLATFORM}.catalog")
        platform = await async_import_module(self.hass, _PLATFORM)
        llm_tools = platform.async_get_tools(self.hass, llm_context, self.id)
        if llm_tools is None:
            # The entry was unloaded after the agent resolved this API.
            raise HomeAssistantError("XBloom machine is no longer available")
        return llm.APIInstance(
            api=self,
            api_prompt=llm_tools.prompt or "",
            llm_context=llm_context,
            tools=llm_tools.tools,
        )


def register_llm_api(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register the XBloom LLM API for a config entry (auto-unregisters on unload)."""
    api = XBloomCoffeeAPI(hass, entry.entry_id, entry.data[CONF_MAC_ADDRESS])
    entry.async_on_unload(llm.async_register_api(hass, api))
    _LOGGER.debug("Registered XBloom LLM API for entry %s", entry.entry_id)
