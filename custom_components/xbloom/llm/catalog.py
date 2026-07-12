"""Catalog of every XBloom LLM tool.

The single place that imports the tool implementations. Kept out of
llm/__init__.py so the platform entry module stays light — this module is
only imported on the XBloom API's success path, pre-warmed in the import
executor by `XBloomCoffeeAPI.async_get_api_instance` (see llm_api.py).

tests/test_llm_prompt.py checks XBLOOM_LLM_PROMPT against this tool list —
update both together when a tool is added/removed/renamed.
"""
from __future__ import annotations

from homeassistant.core import HomeAssistant

from ..coordinator import XBloomCoordinator
from .base import XBloomBaseTool
from .cloud_recipe import (
    XBloomExportRecipeTool,
    XBloomImportCloudRecipeTool,
    XBloomSearchCollectiveRecipesTool,
)
from .local_recipe import (
    XBloomCreateRecipeTool,
    XBloomDeleteRecipeTool,
    XBloomEditRecipeTool,
)
from .pour import XBloomPourTool
from .recipe import (
    XBloomExecuteRecipeTool,
    XBloomGetRecipeTool,
    XBloomListRecipesTool,
)
from .slot import XBloomWriteEasySlotTool
from .status import XBloomStatusTool
from .tare import XBloomTareScaleTool


def build_tools(
    coordinator: XBloomCoordinator, hass: HomeAssistant
) -> list[XBloomBaseTool]:
    """Return fresh instances of every XBloom tool bound to one machine."""
    return [
        XBloomStatusTool(coordinator, hass),
        XBloomListRecipesTool(coordinator, hass),
        XBloomGetRecipeTool(coordinator, hass),
        XBloomCreateRecipeTool(coordinator, hass),
        XBloomEditRecipeTool(coordinator, hass),
        XBloomDeleteRecipeTool(coordinator, hass),
        XBloomPourTool(coordinator, hass),
        XBloomExecuteRecipeTool(coordinator, hass),
        XBloomWriteEasySlotTool(coordinator, hass),
        XBloomTareScaleTool(coordinator, hass),
        XBloomImportCloudRecipeTool(coordinator, hass),
        XBloomSearchCollectiveRecipesTool(coordinator, hass),
        XBloomExportRecipeTool(coordinator, hass),
    ]
