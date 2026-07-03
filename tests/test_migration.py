"""Tests for the v2 -> v3 recipe migration (pure function only)."""
from __future__ import annotations

from custom_components.xbloom import _migrate_recipe_v2_to_v3


def test_v3_injects_uid_and_source():
    migrated = _migrate_recipe_v2_to_v3({"name": "X", "pours": []})
    assert len(migrated["uid"]) == 12
    assert migrated["source"] == "manual"
    # Brew fields untouched.
    assert migrated["name"] == "X"


def test_v3_preserves_existing_metadata():
    recipe = {"name": "X", "uid": "keepme123456", "source": "import", "pours": []}
    migrated = _migrate_recipe_v2_to_v3(recipe)
    assert migrated["uid"] == "keepme123456"
    assert migrated["source"] == "import"


def test_v3_does_not_mutate_input():
    recipe = {"name": "X", "pours": []}
    _migrate_recipe_v2_to_v3(recipe)
    assert "uid" not in recipe
