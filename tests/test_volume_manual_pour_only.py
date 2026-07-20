"""number.volume: default 250 ml, manual/standalone pour only (T10 / E1).

The machine's own pour page defaults to 250 ml (hardware 2026-07-20: the
9001 entry snapshot). Recipe execution must never read the manual-pour
volume — each recipe pour carries its own volume.

AST-based: coordinator/__init__.py imports Home Assistant.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parent.parent / "custom_components" / "xbloom"


def test_volume_defaults_to_250():
    tree = ast.parse((ROOT / "coordinator" / "__init__.py").read_text())
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Attribute)
            and node.target.attr == "volume"
        ):
            assert node.value.value == 250
            return
    raise AssertionError("coordinator volume default not found")


def test_recipe_paths_never_read_manual_pour_volume():
    """Pin the already-true property E1 relies on: the recipe modules
    build volumes from the recipe's own pours, never from the manual-pour
    setpoint."""
    for fname in ("coordinator/recipes.py", "brewing.py"):
        src = (ROOT / fname).read_text()
        assert "self.volume" not in src, fname
        assert "coordinator.volume" not in src, fname
