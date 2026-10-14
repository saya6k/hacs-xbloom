"""The recipe select's empty-store placeholder must be a translation key.

HA translates a select option only when the option *value* matches
entity.select.recipe.state.<key>. The placeholder used to be the literal
"No recipes configured" while the key was "no_recipes_configured", and
only strings.json had the key — so it never translated in any language.
"""
from __future__ import annotations

import json
from pathlib import Path

from custom_components.xbloom.coordinator.recipes import RecipesMixin

COMPONENT = Path(__file__).parent.parent / "custom_components" / "xbloom"


class _Coordinator(RecipesMixin):
    def __init__(self, recipes: dict) -> None:
        self.recipes = recipes


def _key_tree(node: dict, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    for key, value in node.items():
        if isinstance(value, dict):
            keys |= _key_tree(value, f"{prefix}{key}.")
        else:
            keys.add(f"{prefix}{key}")
    return keys


def _load(name: str) -> dict:
    return json.loads((COMPONENT / name).read_text(encoding="utf-8"))


def test_empty_store_placeholder_is_a_translated_state_key():
    (placeholder,) = _Coordinator({}).recipe_names
    for name in ("strings.json", "translations/en.json", "translations/ko.json"):
        states = _load(name)["entity"]["select"]["recipe"]["state"]
        assert placeholder in states, name


def test_real_recipes_replace_the_placeholder():
    assert _Coordinator({"V60": {}, "Tea": {}}).recipe_names == ["V60", "Tea"]


def test_translation_files_share_the_strings_key_tree():
    # Hard rule #3: strings.json and every translations/<lang>.json share
    # one key tree.
    expected = _key_tree(_load("strings.json"))
    for name in ("translations/en.json", "translations/ko.json"):
        assert _key_tree(_load(name)) == expected, name
