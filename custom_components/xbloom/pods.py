"""Pod library — every pod / recipe card this machine has scanned.

A pod's recipe lives on its NFC tag (the machine brews it on its own), and
the hub search can't find pod recipes, so the cloud lookup made when a pod
is scanned (``XBloomCloudClient.fetch_pod_detail``) is the only source of
its bean info and recipes. Kept here, keyed by the tag's xid, as panel data
rather than as recipes — the user saves a pod's recipe to their own
recipes explicitly. One HA store per machine
(``.storage/xbloom_pods_<entry_id>``).
"""
from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

_STORE_VERSION = 1


class PodLibrary:
    """Scanned pods for one machine, newest scan first."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict[str, Any]] = Store(
            hass, _STORE_VERSION, f"xbloom_pods_{entry_id}"
        )
        self._pods: dict[str, dict[str, Any]] = {}

    async def async_load(self) -> None:
        data = await self._store.async_load()
        self._pods = dict((data or {}).get("pods") or {})

    def pods(self) -> list[dict[str, Any]]:
        return sorted(self._pods.values(), key=lambda p: p.get("last_scanned", ""), reverse=True)

    def get(self, xid: str) -> dict[str, Any] | None:
        return self._pods.get(xid)

    async def async_record(self, xid: str, detail: dict[str, Any]) -> None:
        """Count a scan, with whatever the cloud lookup returned.

        An empty ``detail`` (lookup failed — offline, or the cloud API
        down) still records the scan; bean info from an earlier successful
        lookup is kept rather than wiped.
        """
        now = dt_util.utcnow().isoformat()
        previous = self._pods.get(xid) or {}
        self._pods[xid] = {
            **(previous if not detail.get("recipes") else {}),
            **detail,
            "xid": xid,
            "first_scanned": previous.get("first_scanned", now),
            "last_scanned": now,
            "scans": int(previous.get("scans", 0)) + 1,
        }
        await self._async_save()

    async def async_update_detail(self, xid: str, detail: dict[str, Any]) -> bool:
        """Fill in a pod's bean info/recipes from a retried lookup (no scan)."""
        pod = self._pods.get(xid)
        if pod is None or not detail.get("recipes"):
            return False
        keep = {k: pod[k] for k in ("xid", "first_scanned", "last_scanned", "scans") if k in pod}
        self._pods[xid] = {**detail, **keep}
        await self._async_save()
        return True

    async def async_delete(self, xid: str) -> bool:
        if self._pods.pop(xid, None) is None:
            return False
        await self._async_save()
        return True

    async def async_remove(self) -> None:
        """Drop the store file (the config entry is being removed)."""
        await self._store.async_remove()

    async def _async_save(self) -> None:
        await self._store.async_save({"pods": self._pods})
