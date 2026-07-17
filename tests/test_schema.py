"""Tests for custom_components.xbloom.schema pure helpers."""
from __future__ import annotations

import pytest
import voluptuous as vol

from custom_components.xbloom.schema import (
    RECIPE_SCHEMA,
    new_recipe_uid,
    yaml_recipe_uid,
)


def test_recipe_schema_smoke():
    recipe = RECIPE_SCHEMA(
        {
            "name": "Smoke",
            "pours": [{"volume_ml": 100, "temperature_c": 92}],
        }
    )
    assert recipe["name"] == "Smoke"
    assert recipe["pours"][0]["pattern"] == 2
    # Metadata fields are optional — absent unless provided.
    assert "uid" not in recipe


def test_recipe_schema_accepts_metadata():
    recipe = RECIPE_SCHEMA(
        {
            "uid": "abc123def456",
            "cloud_table_id": 12345,
            "share_url": "https://share-h5.xbloom.com/?id=KmMzhYCe5itq",
            "source": "import",
            "name": "Meta",
            "pours": [{"volume_ml": 100, "temperature_c": 92}],
        }
    )
    assert recipe["uid"] == "abc123def456"
    assert recipe["cloud_table_id"] == 12345
    assert recipe["source"] == "import"


def test_new_recipe_uid_format():
    uid = new_recipe_uid()
    assert len(uid) == 12
    assert all(c in "0123456789abcdef" for c in uid)
    assert new_recipe_uid() != uid  # random


def test_yaml_recipe_uid_deterministic():
    assert yaml_recipe_uid("Morning V60") == yaml_recipe_uid("Morning V60")
    assert yaml_recipe_uid("Morning V60") != yaml_recipe_uid("Evening V60")
    assert yaml_recipe_uid("약배전 핫").startswith("yaml-")


@pytest.mark.parametrize("name,expected_c", [("RT", 20), ("bp", 98), ("Bp", 98)])
def test_recipe_schema_accepts_rt_bp_temperature_names(name, expected_c):
    # RT (Room Temperature) / BP (Boiling Point) — the official app's own
    # pour-temperature slider snaps to these exact literal values at its
    # min/max (decompiled 2026-07-17, TemperatureConstant.RT/BP). A plain
    # int (e.g. 92) already worked; this just accepts the app's own names.
    recipe = RECIPE_SCHEMA(
        {"name": "Temp", "pours": [{"volume_ml": 100, "temperature_c": name}]}
    )
    assert recipe["pours"][0]["temperature_c"] == expected_c


def test_recipe_schema_rejects_unknown_temperature_name():
    with pytest.raises(vol.Invalid):
        RECIPE_SCHEMA(
            {"name": "Temp", "pours": [{"volume_ml": 100, "temperature_c": "hot"}]}
        )


def test_recipe_schema_still_accepts_literal_temperature_int():
    recipe = RECIPE_SCHEMA(
        {"name": "Temp", "pours": [{"volume_ml": 100, "temperature_c": 92}]}
    )
    assert recipe["pours"][0]["temperature_c"] == 92
