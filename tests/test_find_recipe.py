"""Tests for schema.find_recipe / share_id_of / dedupe_name."""
from __future__ import annotations

from custom_components.xbloom.schema import dedupe_name, find_recipe, share_id_of

RECIPES = {
    "Morning V60": {
        "uid": "aaa111bbb222",
        "name": "Morning V60",
        "pours": [],
    },
    "Cloud One": {
        "uid": "ccc333ddd444",
        "cloud_table_id": 98765,
        "share_url": "https://share-h5.xbloom.com/?id=KmMzhYCe5itq%2FJcqOLhiag%3D%3D",
        "name": "Cloud One",
        "pours": [],
    },
    "12345": {"uid": "eee555fff666", "name": "12345", "pours": []},
}


def test_find_by_uid():
    assert find_recipe(RECIPES, "aaa111bbb222")[0] == "Morning V60"


def test_find_by_cloud_table_id():
    assert find_recipe(RECIPES, "98765")[0] == "Cloud One"
    assert find_recipe(RECIPES, 98765)[0] == "Cloud One"


def test_find_by_share_url_and_bare_id():
    url = "https://share-h5.xbloom.com/?id=KmMzhYCe5itq%2FJcqOLhiag%3D%3D"
    assert find_recipe(RECIPES, url)[0] == "Cloud One"
    # Bare id, percent-encoded and decoded forms both match.
    assert find_recipe(RECIPES, "KmMzhYCe5itq%2FJcqOLhiag%3D%3D")[0] == "Cloud One"
    assert find_recipe(RECIPES, "KmMzhYCe5itq/JcqOLhiag==")[0] == "Cloud One"


def test_find_by_name():
    assert find_recipe(RECIPES, "Morning V60")[0] == "Morning V60"


def test_priority_table_id_over_name():
    # "12345" is a recipe name, but no cloud_table_id 12345 exists → name wins.
    assert find_recipe(RECIPES, "12345")[0] == "12345"


def test_find_miss():
    assert find_recipe(RECIPES, "nope") is None
    assert find_recipe({}, "aaa111bbb222") is None
    assert find_recipe(RECIPES, "") is None


def test_find_skips_tombstones():
    recipes = {"Gone": None, "Here": {"uid": "abc", "name": "Here"}}
    assert find_recipe(recipes, "Gone") is None
    assert find_recipe(recipes, "abc")[0] == "Here"


def test_share_id_of():
    assert (
        share_id_of("https://share-h5.xbloom.com/?id=Km%2FJcq%3D%3D") == "Km/Jcq=="
    )
    assert share_id_of("Km%2FJcq%3D%3D") == "Km/Jcq=="
    assert share_id_of("https://collective.xbloom.com/recipe/317445") is None
    assert share_id_of("") is None


def test_dedupe_name():
    existing = {"X", "X (2)"}
    assert dedupe_name("Y", existing) == "Y"
    assert dedupe_name("X", existing) == "X (3)"
    assert dedupe_name("X", {"X"}) == "X (2)"
