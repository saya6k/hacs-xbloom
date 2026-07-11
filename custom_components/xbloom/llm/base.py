"""Base tool class for XBloom LLM tools."""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm

from ..coordinator import XBloomCoordinator


class XBloomBaseTool(llm.Tool):
    """Base class for XBloom LLM tools.

    Holds a reference to the coordinator so tools can read state and
    drive BLE actions through the same code path the entities use.
    """

    def __init__(self, coordinator: XBloomCoordinator, hass: HomeAssistant) -> None:
        super().__init__()
        self.coordinator = coordinator
        self.hass = hass
