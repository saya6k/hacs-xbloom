"""Pod library (pods.py) and the panel's pod commands (panel.py)."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from custom_components.xbloom import panel, pods


class _FakeStore:
    saved: dict | None = None

    def __init__(self, hass, version, key) -> None:
        self.key = key

    async def async_load(self):
        return _FakeStore.saved

    async def async_save(self, data):
        _FakeStore.saved = data

    async def async_remove(self):
        _FakeStore.saved = None


def _library():
    _FakeStore.saved = None
    with patch.object(pods, "Store", _FakeStore):
        return pods.PodLibrary(MagicMock(), "e1")


DETAIL = {"name": "Mucho Berry", "image": "https://x/pod.jpg", "recipes": [{"name": "R"}]}


def test_store_is_per_machine():
    with patch.object(pods, "Store", _FakeStore):
        assert pods.PodLibrary(MagicMock(), "abc")._store.key == "xbloom_pods_abc"


def test_record_counts_scans_and_keeps_first_seen():
    lib = _library()
    asyncio.run(lib.async_record("KR0005", DETAIL))
    first = lib.get("KR0005")
    assert first["scans"] == 1 and first["name"] == "Mucho Berry"
    asyncio.run(lib.async_record("KR0005", {**DETAIL, "name": "Renamed"}))
    again = lib.get("KR0005")
    assert again["scans"] == 2
    assert again["first_scanned"] == first["first_scanned"]
    assert again["name"] == "Renamed"  # bean info refreshed from the cloud
    assert _FakeStore.saved["pods"]["KR0005"]["scans"] == 2


def test_list_is_newest_scan_first_and_survives_a_reload():
    lib = _library()
    asyncio.run(lib.async_record("A", DETAIL))
    asyncio.run(lib.async_record("B", DETAIL))
    lib._pods["A"]["last_scanned"] = "2026-01-01T00:00:00+00:00"
    assert [p["xid"] for p in lib.pods()] == ["B", "A"]
    with patch.object(pods, "Store", _FakeStore):
        reloaded = pods.PodLibrary(MagicMock(), "e1")
    asyncio.run(reloaded.async_load())
    assert {p["xid"] for p in reloaded.pods()} == {"A", "B"}


def test_failed_lookup_still_records_the_scan():
    lib = _library()
    asyncio.run(lib.async_record("XB0001", {}))
    pod = lib.get("XB0001")
    assert pod["xid"] == "XB0001" and pod["scans"] == 1
    assert "recipes" not in pod


def test_failed_lookup_keeps_earlier_bean_info():
    lib = _library()
    asyncio.run(lib.async_record("KR0005", DETAIL))
    asyncio.run(lib.async_record("KR0005", {}))  # cloud down on the 2nd scan
    pod = lib.get("KR0005")
    assert pod["name"] == "Mucho Berry" and pod["recipes"] == DETAIL["recipes"]
    assert pod["scans"] == 2


def test_retried_lookup_fills_in_without_counting_a_scan():
    lib = _library()
    asyncio.run(lib.async_record("XB0001", {}))
    assert asyncio.run(lib.async_update_detail("XB0001", {})) is False
    assert asyncio.run(lib.async_update_detail("XB0001", DETAIL)) is True
    pod = lib.get("XB0001")
    assert pod["name"] == "Mucho Berry" and pod["scans"] == 1 and pod["xid"] == "XB0001"
    assert asyncio.run(lib.async_update_detail("NOPE", DETAIL)) is False


def test_delete():
    lib = _library()
    asyncio.run(lib.async_record("A", DETAIL))
    assert asyncio.run(lib.async_delete("A")) is True
    assert asyncio.run(lib.async_delete("A")) is False
    assert lib.pods() == []


# ---- panel commands


def _hass_with(coordinator):
    from custom_components.xbloom.const import DATA_COORDINATOR, DOMAIN

    hass = MagicMock()
    hass.data = {DOMAIN: {"e1": {DATA_COORDINATOR: coordinator}}}
    return hass


def test_ws_pods_lists_the_library():
    coordinator = SimpleNamespace(pod_library=SimpleNamespace(pods=lambda: [{"xid": "A"}]))
    conn = MagicMock()
    panel.ws_pods(_hass_with(coordinator), conn, {"id": 1, "entry_id": "e1"})
    conn.send_result.assert_called_once_with(1, {"pods": [{"xid": "A"}]})


def _save(recipes_store, added):
    pod = {"xid": "A", "recipes": [
        {"name": "R0", "share_url": "https://share-h5.xbloom.com/?id=r0"},
        {"name": "R1", "share_url": "https://share-h5.xbloom.com/?id=r1"},
    ]}
    calls = []
    coordinator = SimpleNamespace(
        pod_library=SimpleNamespace(get=lambda xid: pod if xid == "A" else None),
        save_pod_recipes=lambda recipes: calls.append(recipes) or added,
        recipes=recipes_store,
    )
    return coordinator, calls


def test_ws_save_recipe_saves_the_chosen_one():
    coordinator, calls = _save({}, ["R1"])
    conn = MagicMock()
    panel.ws_pod_save_recipe(_hass_with(coordinator), conn,
                             {"id": 2, "entry_id": "e1", "xid": "A", "index": 1})
    assert calls == [[{"name": "R1", "share_url": "https://share-h5.xbloom.com/?id=r1"}]]
    conn.send_result.assert_called_once_with(2, {"name": "R1", "added": True})


def test_ws_save_recipe_reports_an_existing_copy():
    store = {"My R1": {"name": "My R1", "share_url": "https://share-h5.xbloom.com/?id=r1"}}
    coordinator, _ = _save(store, [])
    conn = MagicMock()
    panel.ws_pod_save_recipe(_hass_with(coordinator), conn,
                             {"id": 3, "entry_id": "e1", "xid": "A", "index": 1})
    conn.send_result.assert_called_once_with(3, {"name": "My R1", "added": False})


def test_ws_save_recipe_unknown_pod_or_index():
    coordinator, _ = _save({}, [])
    for xid, index in (("B", 0), ("A", 5)):
        conn = MagicMock()
        panel.ws_pod_save_recipe(_hass_with(coordinator), conn,
                                 {"id": 4, "entry_id": "e1", "xid": xid, "index": index})
        assert conn.send_error.call_args.args[1] == "not_found"


def _run_refresh(coordinator, xid):
    """Drive ws_pod_refresh's coroutine (async_response hands it to
    hass.async_create_background_task, captured here)."""
    hass = _hass_with(coordinator)
    conn = MagicMock()
    panel.ws_pod_refresh(hass, conn, {"id": 5, "entry_id": "e1", "xid": xid})
    asyncio.run(hass.async_create_background_task.call_args.args[0])
    return conn


def test_ws_refresh_retries_the_lookup():
    lib = _library()
    asyncio.run(lib.async_record("XB0001", {}))

    async def lookup(xid):
        return DETAIL

    coordinator = SimpleNamespace(pod_library=lib, _async_lookup_pod=lookup)
    conn = _run_refresh(coordinator, "XB0001")
    conn.send_result.assert_called_once_with(5, {"updated": True})
    assert lib.get("XB0001")["name"] == "Mucho Berry"


def test_ws_refresh_unknown_pod():
    coordinator = SimpleNamespace(pod_library=_library(), _async_lookup_pod=None)
    conn = _run_refresh(coordinator, "NOPE")
    assert conn.send_error.call_args.args[1] == "not_found"
