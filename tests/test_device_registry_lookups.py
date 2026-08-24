"""Device-registry lookups are scoped to the owning config entry."""

from __future__ import annotations

import json
from pathlib import Path

COMPONENT_ROOT = (
    Path(__file__).resolve().parent.parent / "custom_components" / "xbloom"
)


def test_device_registry_lookups_use_scoped_identifier_api():
    """The unscoped lookup was deprecated in Home Assistant 2026.8."""
    coordinator_sources = (
        (COMPONENT_ROOT / "coordinator" / "__init__.py").read_text(),
        (COMPONENT_ROOT / "coordinator" / "connection.py").read_text(),
    )

    assert all("async_get_device(" not in source for source in coordinator_sources)
    assert sum(
        source.count("async_get_device_by_identifier(")
        for source in coordinator_sources
    ) == 1
    assert "(DOMAIN, self.entry_id), self.entry_id" in coordinator_sources[1]


def test_machine_components_are_registered_as_child_devices():
    """Grinder, scale, and brewer are logical parts of the main machine."""
    coordinator_source = (
        COMPONENT_ROOT / "coordinator" / "__init__.py"
    ).read_text()
    setup_source = (COMPONENT_ROOT / "__init__.py").read_text()

    assert "def _sub_device_info(self, key: str) -> ChildDeviceInfo:" in coordinator_source
    assert "return ChildDeviceInfo(" in coordinator_source
    assert "parent_device_id=self.parent_device_id" in coordinator_source
    assert "via_device=" not in coordinator_source
    assert "suggested_area" not in coordinator_source
    assert "coordinator.parent_device_id = main_device.id" in setup_source


def test_home_assistant_2026_9_minimum_versions_stay_in_sync():
    """HACS, tests, and the devcontainer target the same HA dev build."""
    repository_root = COMPONENT_ROOT.parent.parent
    expected = "2026.9.0.dev202608241354"

    hacs = json.loads((repository_root / "hacs.json").read_text())
    requirements = (repository_root / "requirements_test.txt").read_text()
    devcontainer = json.loads(
        (repository_root / ".devcontainer" / "devcontainer.json").read_text()
    )

    assert hacs["homeassistant"] == expected
    assert f"homeassistant>={expected}" in requirements
    assert devcontainer["image"].endswith(f":{expected}")
