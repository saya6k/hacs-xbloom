"""Scanned pods: recorded in the pod library, saved to recipes on request.

Pod recipes can't be found through the hub search, so the cloud lookup on
pod_detected (fetch_pod_detail) is the only way to get them. The scan is
kept in the pod library (panel data, see pods.py); "save to my recipes"
then stores one recipe, once (user decision 2026-10-15 — auto-saving every
scan as a recipe cluttered the recipe store).

Calls the real RecipesMixin.save_pod_recipes with a minimal stand-in for
`self` (same pattern as tests/test_easy_slot_tea_rejected.py).
"""
from __future__ import annotations

import asyncio

import pytest

from custom_components.xbloom.coordinator.recipes import RecipesMixin
from tests.test_pod_detected_dispatch import _dispatch_pod, _FakeCloud

save_pod_recipes = RecipesMixin.save_pod_recipes


class _Store:
    def __init__(self, recipes: dict | None = None) -> None:
        self.options: dict = dict(recipes or {})
        self.recipes: dict = dict(recipes or {})
        self.writes = 0

    def _options_recipes(self) -> dict:
        return dict(self.options)

    def _write_options_recipes(self, options_recipes: dict) -> None:
        self.writes += 1
        self.options = dict(options_recipes)
        self.recipes = {k: v for k, v in options_recipes.items() if v is not None}


def _pod_recipe(name="Legacy", share="https://share-h5.xbloom.com/?id=abc"):
    return {
        "name": name,
        "dose_g": 15.0,
        "ratio": 16.0,
        "pours": [{"volume_ml": 240, "temperature_c": 93}],
        "share_url": share,
    }


def test_scanned_pod_recipe_is_saved_with_pod_source():
    store = _Store()
    added = save_pod_recipes(store, [_pod_recipe()])
    assert added == ["Legacy"]
    saved = store.recipes["Legacy"]
    assert saved["source"] == "pod"
    assert saved["share_url"] == "https://share-h5.xbloom.com/?id=abc"
    assert len(saved["uid"]) == 12
    assert saved["pours"][0]["volume_ml"] == 240


def test_scanning_the_same_pod_again_adds_nothing():
    store = _Store()
    save_pod_recipes(store, [_pod_recipe()])
    assert save_pod_recipes(store, [_pod_recipe()]) == []
    assert list(store.recipes) == ["Legacy"]
    assert store.writes == 1


def test_already_imported_by_share_link_is_not_duplicated():
    existing = {**_pod_recipe(), "uid": "u1", "source": "import"}
    store = _Store({"Legacy": existing})
    assert save_pod_recipes(store, [_pod_recipe()]) == []
    assert store.writes == 0


def test_different_recipe_with_a_taken_name_gets_a_suffix():
    store = _Store({"Legacy": {"name": "Legacy", "pours": [], "source": "manual"}})
    added = save_pod_recipes(store, [_pod_recipe(share="https://share-h5.xbloom.com/?id=zzz")])
    assert added == ["Legacy (2)"]


def test_recipe_card_saves_each_recipe_once():
    store = _Store()
    cards = [_pod_recipe(n, f"https://share-h5.xbloom.com/?id={i}") for i, n in
             enumerate(("Basic brew", "xPod", "Omni"))]
    assert save_pod_recipes(store, cards) == ["Basic brew", "xPod", "Omni"]
    assert save_pod_recipes(store, cards) == []


def test_recipe_without_share_link_dedupes_by_name_among_pod_saves():
    store = _Store()
    save_pod_recipes(store, [_pod_recipe(share="")])
    assert "share_url" not in store.recipes["Legacy"]
    assert save_pod_recipes(store, [_pod_recipe(share="")]) == []


def test_invalid_recipe_is_skipped_not_raised():
    store = _Store()
    assert save_pod_recipes(store, [{"name": "Broken"}]) == []


class _Library:
    def __init__(self, fail: bool = False) -> None:
        self.recorded: list = []
        self.fail = fail

    async def async_record(self, xid, detail):
        if self.fail:
            raise RuntimeError("store unavailable")
        self.recorded.append((xid, detail))


def _dispatch_with_library(detail, library):
    async def run():
        from tests.test_finish_run_and_pause_gate import _Coordinator

        _Coordinator.pod_library = library
        _Coordinator.save_pod_recipes = lambda self, recipes: pytest.fail("no auto-save")
        try:
            return await _dispatch_pod(_FakeCloud(result=detail))
        finally:
            del _Coordinator.pod_library
            del _Coordinator.save_pod_recipes

    return asyncio.run(run())


def test_pod_detected_records_the_pod_and_saves_no_recipe():
    """The scan goes to the pod library (panel data), not to the recipes —
    the user saves a pod's recipe from the panel explicitly."""
    library = _Library()
    detail = {"name": "Kenya", "default_recipe": "Legacy", "recipes": [_pod_recipe()]}
    _, log = _dispatch_with_library(detail, library)
    assert library.recorded == [("KR0005", detail)]
    assert len(log) == 1  # the event still fired, once


def test_scan_is_recorded_even_when_the_cloud_lookup_fails():
    """User-reported 2026-10-15: a recipe card scan never showed up — the
    cloud API was answering 502, and only a successful lookup was
    recorded. The scan now lands in the library anyway (xid only)."""
    library = _Library()
    _, log = _dispatch_with_library(None, library)  # _FakeCloud(result=None): lookup failed
    assert library.recorded == [("KR0005", {})]
    assert len(log) == 1


def test_a_failing_record_never_swallows_the_event():
    _, log = _dispatch_with_library({"recipes": [_pod_recipe()]}, _Library(fail=True))
    assert len(log) == 1
