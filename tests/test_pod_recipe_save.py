"""A scanned pod's recipes are kept in the local store, once each.

User request 2026-10-14: pod recipes can't be found through the hub
search, so the cloud lookup on pod_detected (fetch_pod_detail) is the only
way to get them — save them the moment a pod is scanned.

Calls the real RecipesMixin.save_pod_recipes with a minimal stand-in for
`self` (same pattern as tests/test_easy_slot_tea_rejected.py).
"""
from __future__ import annotations

import asyncio

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


def test_pod_detected_with_recipes_triggers_the_save_and_still_fires():
    saved: list = []
    detail = {"name": "Kenya", "default_recipe": "Legacy", "recipes": [_pod_recipe()]}

    async def run():
        from tests.test_finish_run_and_pause_gate import _Coordinator

        _Coordinator.save_pod_recipes = lambda self, recipes: saved.append(recipes)
        try:
            return await _dispatch_pod(_FakeCloud(result=detail))
        finally:
            del _Coordinator.save_pod_recipes

    _, log = asyncio.run(run())
    assert saved == [detail["recipes"]]
    assert len(log) == 1  # the event still fired, once


def test_a_failing_save_never_swallows_the_event():
    detail = {"recipes": [_pod_recipe()]}

    async def run():
        from tests.test_finish_run_and_pause_gate import _Coordinator

        def boom(self, recipes):
            raise RuntimeError("store unavailable")

        _Coordinator.save_pod_recipes = boom
        try:
            return await _dispatch_pod(_FakeCloud(result=detail))
        finally:
            del _Coordinator.save_pod_recipes

    _, log = asyncio.run(run())
    assert len(log) == 1
