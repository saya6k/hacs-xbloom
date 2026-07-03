"""Tests for custom_components.xbloom.schema pure helpers."""
from __future__ import annotations

from custom_components.xbloom.schema import RECIPE_SCHEMA


def test_recipe_schema_smoke():
    recipe = RECIPE_SCHEMA(
        {
            "name": "Smoke",
            "pours": [{"volume_ml": 100, "temperature_c": 92}],
        }
    )
    assert recipe["name"] == "Smoke"
    assert recipe["pours"][0]["pattern"] == 2
