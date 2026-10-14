"""Sidebar panel — a self-contained management UI modeled on the official app.

The panel is a single, build-free web component (``frontend/xbloom-panel.js``)
served from this package. It reads live state straight from the entities
and acts through the existing entities/services, so the only backend it
needs is one read-only websocket command: ``xbloom/machines``, which hands
it each machine's entity map plus the full recipe store (``list_recipes``
only returns summaries — the editor needs the pours).

Registered once from ``async_setup`` — the panel is global, not per entry;
it lists every configured machine and lets the user switch between them.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.components import panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .const import CONF_MAC_ADDRESS, DATA_COORDINATOR, DOMAIN

PANEL_URL_PATH = "xbloom"
PANEL_ICON = "mdi:coffee-maker"
PANEL_TITLE = "XBloom"
_WEBCOMPONENT = "xbloom-panel"
_STATIC_URL = "/xbloom_static"
_FRONTEND_DIR = Path(__file__).parent / "frontend"
_PANEL_FILE = "xbloom-panel.js"


def _file_hash(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()[:10]


async def async_register_panel(hass: HomeAssistant) -> None:
    """Serve the panel bundle, add the sidebar entry and its websocket API."""
    await hass.http.async_register_static_paths(
        [StaticPathConfig(_STATIC_URL, str(_FRONTEND_DIR), cache_headers=False)]
    )
    # Content hash as a cache-buster — the manifest version is 0.0.0 in
    # the repo, so it can't tell two builds of the panel apart.
    version = await hass.async_add_executor_job(_file_hash, _FRONTEND_DIR / _PANEL_FILE)
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=_WEBCOMPONENT,
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        module_url=f"{_STATIC_URL}/{_PANEL_FILE}?v={version}",
        require_admin=False,
    )
    websocket_api.async_register_command(hass, ws_machines)


def _machine_payload(hass: HomeAssistant, entry_id: str, coordinator: Any) -> dict:
    entry = hass.config_entries.async_get_entry(entry_id)
    # "<domain>.<translation_key>" -> entity_id, so the panel never has to
    # guess (or hardcode) entity ids the user may have renamed.
    entities = {
        f"{ent.domain}.{ent.translation_key}": ent.entity_id
        for ent in er.async_entries_for_config_entry(er.async_get(hass), entry_id)
        if ent.translation_key and not ent.disabled_by
    }
    recipes = [
        {**recipe, "name": name}
        for name, recipe in (coordinator.recipes or {}).items()
        if isinstance(recipe, dict)
    ]
    return {
        "entry_id": entry_id,
        "title": entry.title if entry else coordinator.mac_address,
        "mac": entry.data.get(CONF_MAC_ADDRESS) if entry else coordinator.mac_address,
        "entities": entities,
        "recipes": recipes,
        "selected_recipe": coordinator.selected_recipe,
        "easy_slots": {
            letter: coordinator.easy_slot_contents(letter) for letter in ("A", "B", "C")
        },
        "cloud_login": coordinator.cloud_login_configured,
    }


@websocket_api.websocket_command({vol.Required("type"): "xbloom/machines"})
@callback
def ws_machines(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Every configured machine with its entity map and full recipe store."""
    machines = [
        _machine_payload(hass, entry_id, data[DATA_COORDINATOR])
        for entry_id, data in hass.data.get(DOMAIN, {}).items()
        if isinstance(data, dict) and DATA_COORDINATOR in data
    ]
    connection.send_result(msg["id"], {"machines": machines})
