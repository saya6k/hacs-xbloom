"""Shared entity helpers.

Unique ids are scoped to the config entry so more than one machine can be
set up: each entity class keeps its historical, machine-independent id
(``"xbloom_grind"`` …) as a class attribute, and the platforms prefix it
with the entry id when they add the entities. Entries created before this
change are moved over by ``async_migrate_entry`` (config entry 3.2), which
rewrites only the registry's unique ids — entity ids, names, areas and
history stay as they are.
"""
from __future__ import annotations

from collections.abc import Iterable

from homeassistant.helpers.entity import Entity


def scoped_unique_id(entry_id: str, unique_id: str) -> str:
    """The per-machine form of a historical unique id."""
    return f"{entry_id}_{unique_id}"


def scope_unique_ids(entry_id: str, entities: Iterable[Entity]) -> list[Entity]:
    """Prefix every entity's unique id with its config entry id."""
    scoped = list(entities)
    for entity in scoped:
        entity._attr_unique_id = scoped_unique_id(entry_id, entity._attr_unique_id)
    return scoped
