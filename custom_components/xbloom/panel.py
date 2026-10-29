"""Sidebar panel — a self-contained management UI modeled on the official app.

The panel is a single, build-free web component (``frontend/xbloom-panel.js``)
served from this package. It reads live state straight from the entities
and acts through the existing entities/services, so the only backend it
needs is a few websocket commands: ``xbloom/machines``, which hands it each
machine's entity map plus the full recipe store (``list_recipes`` only
returns summaries — the editor needs the pours), ``xbloom/cloud_search``, a
paged collective-hub search, and ``xbloom/pods*`` for the pod library
(list, save one of a pod's recipes, forget a pod).

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

from .const import CONF_MAC_ADDRESS, CONF_STORE_REGION, DATA_COORDINATOR, DOMAIN
from .machine_color import color_from_serial
from .schema import find_recipe
from .stores import STORE_REGIONS, STORES, effective_region, region_for_country

PANEL_URL_PATH = "xbloom"
PANEL_ICON = "mdi:coffee-maker"
PANEL_TITLE = "xBloom"
_WEBCOMPONENT = "xbloom-panel"
_STATIC_URL = "/xbloom_static"
_FRONTEND_DIR = Path(__file__).parent / "frontend"
_PANEL_FILE = "xbloom-panel.js"
_BRAND_DIR = Path(__file__).parent / "brand"

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
    websocket_api.async_register_command(hass, ws_cloud_detail)
    websocket_api.async_register_command(hass, ws_set_store_region)
    websocket_api.async_register_command(hass, ws_pods)
    websocket_api.async_register_command(hass, ws_pod_save_recipe)
    websocket_api.async_register_command(hass, ws_pod_delete)
    websocket_api.async_register_command(hass, ws_pod_refresh)


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
        # None when the code is unknown — the panel falls back to black.
        "detected_color": color_from_serial(_machine_serial(hass, coordinator)),
        # xBloom's own photo for this serial (cloud login only) — preferred
        # over the per-colour store photo, as in the official app.
        "cover_url": coordinator.machine_cover_url,
        # The machine's own display unit (g/oz/ml) — the scale sensor is
        # always grams, so the panel converts to match the machine screen.
        "weight_unit": getattr(coordinator, "_weight_unit", "g"),
        **_store_payload(hass, entry),
    }


def _store_payload(hass: HomeAssistant, entry: Any) -> dict:
    """The panel's store region: the user's choice or, by default, the one
    Home Assistant's country implies (the app's own region rule)."""
    setting = entry.options.get(CONF_STORE_REGION) if entry else None
    region = effective_region(setting, hass.config.country)
    return {
        "store_region_setting": setting if setting in STORE_REGIONS else "auto",
        "store_region": region,
        "store_auto_region": region_for_country(hass.config.country),
        "store": STORES[region],
    }


@websocket_api.websocket_command(
    {
        vol.Required("type"): "xbloom/set_store_region",
        vol.Required("entry_id"): str,
        # "auto" follows Home Assistant's country.
        vol.Required("region"): vol.In(("auto", *STORE_REGIONS)),
    }
)
@callback
def ws_set_store_region(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Save which XBloom web store the panel's shop links open."""
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None or entry.domain != DOMAIN:
        connection.send_error(msg["id"], "not_found", "No xBloom machine with that entry id.")
        return
    options = {k: v for k, v in entry.options.items() if k != CONF_STORE_REGION}
    if msg["region"] != "auto":
        options[CONF_STORE_REGION] = msg["region"]
    hass.config_entries.async_update_entry(entry, options=options)
    connection.send_result(msg["id"], _store_payload(hass, entry))


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


def _coordinator(hass: HomeAssistant, entry_id: str) -> Any | None:
    data = hass.data.get(DOMAIN, {}).get(entry_id)
    return data[DATA_COORDINATOR] if isinstance(data, dict) and DATA_COORDINATOR in data else None


@websocket_api.websocket_command(
    {vol.Required("type"): "xbloom/pods", vol.Required("entry_id"): str}
)
@callback
def ws_pods(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """The machine's pod library — every pod scanned, newest first."""
    coordinator = _coordinator(hass, msg["entry_id"])
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "No xBloom machine with that entry id.")
        return
    connection.send_result(msg["id"], {"pods": coordinator.pod_library.pods()})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "xbloom/pods/save_recipe",
        vol.Required("entry_id"): str,
        vol.Required("xid"): str,
        vol.Required("index"): vol.All(int, vol.Range(min=0)),
    }
)
@callback
def ws_pod_save_recipe(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Save one of a pod's recipes to the local recipes ("save to my recipes")."""
    coordinator = _coordinator(hass, msg["entry_id"])
    pod = coordinator.pod_library.get(msg["xid"]) if coordinator else None
    recipes = (pod or {}).get("recipes") or []
    if msg["index"] >= len(recipes):
        connection.send_error(msg["id"], "not_found", "No such pod recipe.")
        return
    recipe = recipes[msg["index"]]
    added = coordinator.save_pod_recipes([recipe])
    # Already saved earlier: report the local copy's name instead.
    existing = find_recipe(coordinator.recipes or {}, recipe.get("share_url") or "")
    name = added[0] if added else (existing[0] if existing else recipe.get("name"))
    connection.send_result(msg["id"], {"name": name, "added": bool(added)})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "xbloom/pods/refresh",
        vol.Required("entry_id"): str,
        vol.Required("xid"): str,
    }
)
@websocket_api.async_response
async def ws_pod_refresh(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Retry the cloud lookup for a pod scanned while it failed."""
    coordinator = _coordinator(hass, msg["entry_id"])
    if coordinator is None or coordinator.pod_library.get(msg["xid"]) is None:
        connection.send_error(msg["id"], "not_found", "No such pod.")
        return
    detail = await coordinator._async_lookup_pod(msg["xid"])
    updated = await coordinator.pod_library.async_update_detail(msg["xid"], detail)
    connection.send_result(msg["id"], {"updated": updated})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "xbloom/pods/delete",
        vol.Required("entry_id"): str,
        vol.Required("xid"): str,
    }
)
@websocket_api.async_response
async def ws_pod_delete(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Forget a pod (its saved recipes, if any, stay)."""
    coordinator = _coordinator(hass, msg["entry_id"])
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "No xBloom machine with that entry id.")
        return
    connection.send_result(
        msg["id"], {"deleted": await coordinator.pod_library.async_delete(msg["xid"])}
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "xbloom/cloud_detail",
        vol.Required("entry_id"): str,
        vol.Required("community_recipe_id"): vol.All(int, vol.Range(min=1)),
    }
)
@websocket_api.async_response
async def ws_cloud_detail(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """A hub recipe's detail page, plus the store link for an official one."""
    coordinator = _coordinator(hass, msg["entry_id"])
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "No xBloom machine with that entry id.")
        return
    client = coordinator.cloud_client
    detail = await client.fetch_collective_detail(msg["community_recipe_id"])
    if detail is None:
        connection.send_error(msg["id"], "fetch_failed", "Could not load that recipe from the hub.")
        return
    store = _store_payload(hass, hass.config_entries.async_get_entry(msg["entry_id"]))
    # Product-level links only exist for xbloom.com (see stores.py); the
    # Korean and Chinese stores get a link to their xPod page / home.
    if store["store_region"] == "global":
        if detail.get("official"):
            detail["product_url"] = await client.find_store_product(detail.get("name"))
    else:
        detail["store_url"] = store["store"]["pods"]
    detail["store_region"] = store["store_region"]
    connection.send_result(msg["id"], detail)


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
        connection.send_error(msg["id"], "not_found", "No xBloom machine with that entry id.")
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
