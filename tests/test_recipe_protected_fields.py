"""Tests for schema.strip_protected_recipe_fields.

Reproduces two real gaps found in coordinator.py: create_local_recipe
never stripped cloud_table_id/share_url from user-supplied create_recipe
YAML at all, and async_edit_local_recipe's "restore the original value"
loop only fired when the current recipe already had a non-None value for
uid/cloud_table_id/share_url/source — a recipe that had never been
exported (no cloud_table_id yet) let `changes` inject one straight
through. Either way a user (or a script) could spoof/steal cloud
identity via create_recipe/edit_recipe's raw YAML fields, e.g. pointing
cloud_export_recipe at someone else's cloud_table_id.
"""
from __future__ import annotations

from custom_components.xbloom.schema import (
    RECIPE_PROTECTED_FIELDS,
    strip_protected_recipe_fields,
)


def test_strips_all_protected_fields():
    recipe = {
        "uid": "spoofed",
        "cloud_table_id": 99999,
        "share_url": "https://share-h5.xbloom.com/?id=notmine",
        "source": "seed_cloud",
        "name": "Test",
        "pours": [{"volume_ml": 100, "temperature_c": 92}],
    }
    cleaned = strip_protected_recipe_fields(recipe)
    for key in RECIPE_PROTECTED_FIELDS:
        assert key not in cleaned
    assert cleaned["name"] == "Test"
    assert cleaned["pours"] == recipe["pours"]


def test_does_not_mutate_input():
    recipe = {"uid": "x", "name": "Test", "pours": []}
    strip_protected_recipe_fields(recipe)
    assert recipe["uid"] == "x"  # original dict untouched


def test_noop_when_no_protected_fields_present():
    recipe = {"name": "Test", "pours": []}
    assert strip_protected_recipe_fields(recipe) == recipe


def test_edit_merge_cannot_inject_cloud_table_id_absent_on_current():
    # The exact bug: current has no cloud_table_id yet (never exported);
    # changes tries to inject one. Merging with stripped changes must
    # leave it absent, matching current — not adopt the injected value.
    current = {"uid": "real-uid", "name": "Test", "pours": []}
    changes = {"cloud_table_id": 99999, "name": "Renamed"}
    merged = {**current, **strip_protected_recipe_fields(changes)}
    assert "cloud_table_id" not in merged
    assert merged["uid"] == "real-uid"
    assert merged["name"] == "Renamed"


def test_edit_merge_cannot_overwrite_existing_uid():
    current = {"uid": "real-uid", "cloud_table_id": 111, "name": "Test", "pours": []}
    changes = {"uid": "spoofed", "cloud_table_id": 99999}
    merged = {**current, **strip_protected_recipe_fields(changes)}
    assert merged["uid"] == "real-uid"
    assert merged["cloud_table_id"] == 111
