"""Sidebar panel — a self-contained management UI modeled on the official app.

The panel is a single, build-free web component (``frontend/xbloom-panel.js``)
served from this package. It reads live state straight from the entities
and acts through the existing entities/services, so the only backend it
needs is a few websocket commands: ``xbloom/machines``, which hands it each
machine's entity map plus the full recipe store (``list_recipes`` only
returns summaries — the editor needs the pours), ``xbloom/cloud_search``, a
paged collective-hub search, and ``xbloom/set_machine_color``, which saves
the colour behind the product photo.

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
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import CONF_MAC_ADDRESS, CONF_MACHINE_COLOR, DATA_COORDINATOR, DOMAIN

PANEL_URL_PATH = "xbloom"
PANEL_ICON = "mdi:coffee-maker"
PANEL_TITLE = "XBloom"
_WEBCOMPONENT = "xbloom-panel"
_STATIC_URL = "/xbloom_static"
_FRONTEND_DIR = Path(__file__).parent / "frontend"
_PANEL_FILE = "xbloom-panel.js"
_BRAND_DIR = Path(__file__).parent / "brand"

# Studio colours sold (xbloom.com store, 2026-10); the panel shows the
# matching product photo.
MACHINE_COLORS = (
    "midnight_black",
    "moonlight_white",
    "sage_green_green",
    "sage_green_gold",
    "twilight",
    "offline_blue",
)
# The official app's own rule (jadx 2026-10-14, Device.getHomeImageRes):
# serialNumber[4:6] "02" shows the white machine, anything else the black
# one. It knows no other colour codes, so neither do we — the rest is the
# user's pick.
_SERIAL_COLOR_CODES = {"01": "midnight_black", "02": "moonlight_white"}


def color_from_serial(serial: str | None) -> str | None:
    """The machine colour the serial number encodes, if the app knows it."""
    if not serial or len(serial) < 6:
        return None
    return _SERIAL_COLOR_CODES.get(serial[4:6])


def _machine_serial(hass: HomeAssistant, coordinator: Any) -> str | None:
    """Live serial when connected, else the one kept on the device entry
    (the link is dropped in idle standby)."""
    serial = (coordinator.data or {}).get("serial_number")
    if serial:
        return serial
    device_id = getattr(coordinator, "parent_device_id", None)
    device = dr.async_get(hass).async_get(device_id) if device_id else None
    return device.serial_number if device else None


def _file_hash(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()[:10]


async def async_register_panel(hass: HomeAssistant) -> None:
    """Serve the panel bundle, add the sidebar entry and its websocket API."""
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(_STATIC_URL, str(_FRONTEND_DIR), cache_headers=False),
            # The panel header uses the integration's own wordmark.
            StaticPathConfig("/xbloom_brand", str(_BRAND_DIR), cache_headers=True),
        ]
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
    websocket_api.async_register_command(hass, ws_cloud_search)
    websocket_api.async_register_command(hass, ws_set_machine_color)


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
        # None = auto (detected_color, falling back to black in the panel).
        "machine_color": entry.options.get(CONF_MACHINE_COLOR) if entry else None,
        "detected_color": color_from_serial(_machine_serial(hass, coordinator)),
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


@websocket_api.websocket_command(
    {
        vol.Required("type"): "xbloom/set_machine_color",
        vol.Required("entry_id"): str,
        # None goes back to auto-detection.
        vol.Required("color"): vol.Any(None, vol.In(MACHINE_COLORS)),
    }
)
@callback
def ws_set_machine_color(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Save the machine's colour (a no-reload option — see __init__)."""
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None or entry.domain != DOMAIN:
        connection.send_error(msg["id"], "not_found", "No XBloom machine with that entry id.")
        return
    options = {k: v for k, v in entry.options.items() if k != CONF_MACHINE_COLOR}
    if msg["color"]:
        options[CONF_MACHINE_COLOR] = msg["color"]
    hass.config_entries.async_update_entry(entry, options=options)
    connection.send_result(msg["id"], {"machine_color": msg["color"]})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "xbloom/cloud_search",
        vol.Required("entry_id"): str,
        vol.Optional("keyword"): str,
        vol.Optional("category"): vol.In(["coffee", "tea"]),
        vol.Optional("src"): vol.In(["official", "user"]),
        vol.Optional("sort", default="likes"): vol.In(["date", "likes", "downloads"]),
        vol.Optional("page", default=1): vol.All(int, vol.Range(min=1)),
    }
)
@websocket_api.async_response
async def ws_cloud_search(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Search the public collective hub, one page at a time.

    The ``cloud_search_collective_recipes`` service only returns the first
    page; the panel's "load more" needs ``page``. Importing a result goes
    through the regular ``cloud_import_recipe`` service.
    """
    data = hass.data.get(DOMAIN, {}).get(msg["entry_id"])
    if not isinstance(data, dict) or DATA_COORDINATOR not in data:
        connection.send_error(msg["id"], "not_found", "No XBloom machine with that entry id.")
        return
    result = await data[DATA_COORDINATOR].async_search_collective_recipes(
        keyword=msg.get("keyword") or None,
        category=msg.get("category"),
        src=msg.get("src"),
        sort=msg["sort"],
        sort_direction="desc",
        page=msg["page"],
    )
    if not result.get("success"):
        connection.send_error(msg["id"], "search_failed", result.get("message", "Search failed."))
        return
    connection.send_result(
        msg["id"],
        {
            "recipes": result["list"],
            "page": result.get("page_index") or msg["page"],
            "total_page": result.get("total_page") or 1,
            "total": result.get("total"),
        },
    )
