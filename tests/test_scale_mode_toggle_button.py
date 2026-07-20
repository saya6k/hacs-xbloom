"""Single scale-mode toggle button (T8).

Replaces the separate enter/exit scale-mode buttons with one
`button.scale_mode` that enters or exits based on the telemetry-derived
`standalone_scale` state, flipping its icon accordingly (the pause-button
pattern). AST-based — button.py imports Home Assistant, which the
pure-logic test env doesn't have.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent / "custom_components" / "xbloom"


def _button_classes():
    tree = ast.parse((ROOT / "button.py").read_text())
    return {n.name: n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}


def _class_source(name: str) -> str:
    return ast.get_source_segment((ROOT / "button.py").read_text(), _button_classes()[name])


def test_toggle_button_replaces_enter_exit_pair():
    classes = _button_classes()
    assert "XBloomScaleModeButton" in classes
    assert "XBloomEnterScaleModeButton" not in classes
    assert "XBloomExitScaleModeButton" not in classes


def test_toggle_button_branches_on_standalone_scale():
    src = _class_source("XBloomScaleModeButton")
    assert "standalone_scale" in src
    assert "async_exit_scale_mode" in src
    assert "async_enter_scale_mode" in src
    # Dynamic icon in-class (allowed for state-dependent icons, like the
    # pause button) — one icon per direction.
    assert "def icon" in src


def test_translation_keys_swapped_in_all_three_files():
    for fname in ("strings.json", "translations/en.json", "translations/ko.json"):
        data = json.loads((ROOT / fname).read_text())
        buttons = data["entity"]["button"]
        assert "scale_mode" in buttons, fname
        assert "enter_scale_mode" not in buttons, fname
        assert "exit_scale_mode" not in buttons, fname


def test_icons_json_swapped():
    """The dynamic icon lives in the class — icons.json must not carry a
    static default for it (hard rule: one source per icon), and the old
    keys must be gone."""
    data = json.loads((ROOT / "icons.json").read_text())
    buttons = data["entity"]["button"]
    assert "enter_scale_mode" not in buttons
    assert "exit_scale_mode" not in buttons
    assert "scale_mode" not in buttons
