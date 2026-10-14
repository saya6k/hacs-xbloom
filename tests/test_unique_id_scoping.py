"""Per-entry unique ids (multi-machine support) and the 3.1 -> 3.2 migration.

Unique ids used to be fixed strings, so a second machine's entities
collided with the first's. They are now prefixed with the config entry
id; the migration rewrites only the registry's unique id, never the
entity id.
"""
from __future__ import annotations

from types import SimpleNamespace

from custom_components.xbloom import _scope_unique_id_migration
from custom_components.xbloom.config_flow import XBloomConfigFlow
from custom_components.xbloom.entity import scope_unique_ids, scoped_unique_id


class _Entity:
    def __init__(self, unique_id):
        self._attr_unique_id = unique_id


def test_scope_unique_ids_prefixes_each_entity():
    entities = scope_unique_ids("entryA", [_Entity("xbloom_grind"), _Entity("xbloom_state")])
    assert [e._attr_unique_id for e in entities] == ["entryA_xbloom_grind", "entryA_xbloom_state"]


def test_two_machines_get_distinct_unique_ids():
    a = scope_unique_ids("entryA", [_Entity("xbloom_grind")])[0]._attr_unique_id
    b = scope_unique_ids("entryB", [_Entity("xbloom_grind")])[0]._attr_unique_id
    assert a != b


def test_migration_scopes_legacy_ids_only():
    migrate = _scope_unique_id_migration("entryA")
    legacy = SimpleNamespace(unique_id="xbloom_grind", entity_id="button.xbloom_grind")
    assert migrate(legacy) == {"new_unique_id": "entryA_xbloom_grind"}
    # Already scoped (re-run, or a fresh install): left alone.
    assert migrate(SimpleNamespace(unique_id=scoped_unique_id("entryA", "xbloom_grind"))) is None


def test_migration_never_touches_entity_id():
    migrate = _scope_unique_id_migration("entryA")
    changes = migrate(SimpleNamespace(unique_id="xbloom_state", entity_id="sensor.my_coffee"))
    assert set(changes) == {"new_unique_id"}


def test_config_flow_creates_entries_at_the_migrated_version():
    assert (XBloomConfigFlow.VERSION, XBloomConfigFlow.MINOR_VERSION) == (3, 2)
