"""Device-registry lookups are scoped to the owning config entry."""

from __future__ import annotations

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
    ) == 2
    assert all(
        "(DOMAIN, self.entry_id), self.entry_id" in source
        for source in coordinator_sources
    )
