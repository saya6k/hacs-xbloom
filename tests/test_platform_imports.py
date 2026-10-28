"""Names are imported from where Home Assistant defines them.

HA 2026.11.0b0 stopped re-exporting ``EntityCategory`` from
``homeassistant.components.sensor``, and ``sensor.py`` imported it from
there, so the whole entry failed to set up (``ImportError: cannot import
name 'EntityCategory'``). The tests run on the 2026.10.0b0 floor, where
the re-export still existed, so nothing caught it. This flags any class,
enum or function imported from ``homeassistant.components.<x>`` that is
really defined elsewhere in Home Assistant.
"""
from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

_PACKAGE = Path(__file__).parent.parent / "custom_components" / "xbloom"


def _component_imports() -> list[tuple[str, str, str]]:
    found = []
    for path in sorted(_PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith("homeassistant.components.")
            ):
                rel = str(path.relative_to(_PACKAGE))
                found.extend((rel, node.module, alias.name) for alias in node.names)
    return found


@pytest.mark.parametrize(("source", "module", "name"), _component_imports())
def test_component_import_is_not_a_re_export(source, module, name):
    imported = getattr(importlib.import_module(module), name, None)
    defined_in = getattr(imported, "__module__", None)
    if defined_in is None:
        # A plain constant (str/int) carries no module; nothing to check.
        return
    package = module.rsplit(".", 1)[0] if module.count(".") > 2 else module
    if not defined_in.startswith("homeassistant."):
        # A third-party library the component deliberately re-exports as its
        # API (e.g. bluetooth's BluetoothServiceInfoBleak from habluetooth).
        return
    assert defined_in.startswith(package), (
        f"{source} imports {name} from {module}, but it is defined in "
        f"{defined_in}; import it from there"
    )
