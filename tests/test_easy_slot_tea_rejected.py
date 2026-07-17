"""Tests for coordinator.recipes.RecipesMixin.async_write_easy_slot refusing
tea recipes.

Hardware-reported 2026-07-18: a chamomile (tea) recipe written to an Easy
Mode slot ground beans when run from the machine's physical slot button.
Root cause: async_write_easy_slot had no cup_type awareness at all —
brewing.async_write_easy_slots always builds the coffee-shaped 8001/8004
recipe payload (11510 has no dedicated tea slot format), and its
grinder_on flag comes from grind_size/dose_g, which RECIPE_SCHEMA
defaults to 50/15.0g — coffee-oriented defaults a casually-authored tea
recipe (cup_type: tea, no explicit grind_size/dose_g) never overrides.
Even a correctly zeroed tea recipe still can't brew as real tea from a
slot (no siphon/soak — only 4513/4512 does that), so the fix is to
refuse the write outright rather than try to sanitize the payload.

Calls the real unbound method off RecipesMixin with a minimal duck-typed
stand-in for `self` — the check runs before any connection/BLE work, so
only `.recipes` / `.selected_recipe` are needed (same pattern as
tests/test_wake_retry.py).
"""
from __future__ import annotations

import asyncio

from custom_components.xbloom.coordinator.recipes import RecipesMixin

_async_write_easy_slot = RecipesMixin.async_write_easy_slot


class _FakeSelf:
    def __init__(self, recipes: dict, selected_recipe: str | None) -> None:
        self.recipes = recipes
        self.selected_recipe = selected_recipe

    def _check_connected(self) -> bool:
        # Not under test here — False lets the coffee-recipe test observe
        # that the tea guard let it fall through to the *next* gate,
        # without needing a real connected client.
        return False


def test_tea_recipe_in_selected_slot_is_refused():
    recipes = {
        "Chamomile": {
            "name": "Chamomile",
            "cup_type": "tea",
            "grind_size": 50,
            "dose_g": 15.0,
            "pours": [{"volume_ml": 120, "temperature_c": 80, "pause_seconds": 60}],
        }
    }
    fake_self = _FakeSelf(recipes, selected_recipe="Chamomile")

    result = asyncio.run(_async_write_easy_slot(fake_self, "A"))

    assert result["success"] is False
    assert result["error"] == "tea_not_supported_in_easy_slot"


def test_tea_recipe_by_identifier_is_refused():
    recipes = {
        "Chamomile": {
            "name": "Chamomile",
            "cup_type": "tea",
            "pours": [{"volume_ml": 120, "temperature_c": 80, "pause_seconds": 60}],
        }
    }
    fake_self = _FakeSelf(recipes, selected_recipe=None)

    result = asyncio.run(
        _async_write_easy_slot(fake_self, "B", identifier="Chamomile")
    )

    assert result["success"] is False
    assert result["error"] == "tea_not_supported_in_easy_slot"


def test_coffee_recipe_is_not_refused_by_the_tea_check():
    recipes = {
        "V60": {
            "name": "V60",
            "cup_type": "omni_dripper",
            "grind_size": 35,
            "dose_g": 18.0,
            "pours": [{"volume_ml": 250, "temperature_c": 93, "pause_seconds": 30}],
        }
    }
    fake_self = _FakeSelf(recipes, selected_recipe="V60")

    result = asyncio.run(_async_write_easy_slot(fake_self, "A"))

    # Falls through past the tea check to the connectivity check next —
    # proves the tea guard doesn't misfire on an ordinary coffee recipe.
    assert result["error"] == "not_connected"
