"""LLM tools platform for the XBloom Coffee Machine integration.

Discovered lazily by Home Assistant's `llm` integration (HA ≥ 2026.8) the
first time any LLM API collects tools. This entry module MUST stay light:
no tool/catalog/`homeassistant.components.llm` imports at module level, so
that a foreign API's collection (e.g. Assist — which calls every platform
and skips our None) never loads the tool implementations, and so the module
still imports on pre-2026.8 hosts running the pure-logic test suite.

The function-level imports below are cache hits in normal operation:
`XBloomCoffeeAPI.async_get_api_instance` pre-imports the catalog in the
import executor before calling this callback (see llm_api.py), and
`homeassistant.components.llm` is always loaded by our caller.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant, callback

from ..const import DATA_COORDINATOR, DOMAIN, XBLOOM_LLM_API_ID, XBLOOM_LLM_PROMPT

if TYPE_CHECKING:
    from homeassistant.components.llm import LLMTools
    from homeassistant.helpers.llm import LLMContext

_API_ID_PREFIX = f"{XBLOOM_LLM_API_ID}_"


@callback
def async_get_tools(
    hass: HomeAssistant, llm_context: LLMContext, api_id: str
) -> LLMTools | None:
    """Return XBloom tools for one of our per-entry API ids, else None.

    Returning None opts us out of Assist and every other API — the XBloom
    tools only ever surface through the user-selected XBloom custom API.
    """
    if not api_id.startswith(_API_ID_PREFIX):
        return None
    entry_id = api_id[len(_API_ID_PREFIX) :]
    entry_data = hass.data.get(DOMAIN, {}).get(entry_id)
    if not isinstance(entry_data, dict) or DATA_COORDINATOR not in entry_data:
        # Unknown id, or the entry was unloaded since the API was requested.
        return None

    from homeassistant.components.llm import LLMTools
    from .catalog import build_tools

    return LLMTools(
        tools=build_tools(entry_data[DATA_COORDINATOR], hass),
        prompt=XBLOOM_LLM_PROMPT,
    )
