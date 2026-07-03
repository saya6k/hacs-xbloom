"""Tests for schema.scale_pours_to_total."""
from __future__ import annotations

from custom_components.xbloom.schema import scale_pours_to_total


def _pours(*volumes):
    return [{"volume_ml": v, "temperature_c": 92} for v in volumes]


def test_scale_up_exact_sum():
    scaled = scale_pours_to_total(_pours(50, 100, 100), 300)
    assert [p["volume_ml"] for p in scaled] == [60, 120, 120]
    assert sum(p["volume_ml"] for p in scaled) == 300


def test_scale_down_residue_absorbed_by_last():
    # 3 × 100 → 250: 83.33… each; last pour absorbs the rounding residue.
    scaled = scale_pours_to_total(_pours(100, 100, 100), 250)
    assert sum(p["volume_ml"] for p in scaled) == 250
    assert scaled[0]["volume_ml"] == 83
    assert scaled[1]["volume_ml"] == 83
    assert scaled[2]["volume_ml"] == 84


def test_single_pour():
    scaled = scale_pours_to_total(_pours(240), 255)
    assert [p["volume_ml"] for p in scaled] == [255]


def test_empty_and_degenerate():
    assert scale_pours_to_total([], 300) == []
    unchanged = scale_pours_to_total(_pours(0, 0), 300)
    assert [p["volume_ml"] for p in unchanged] == [0, 0]
    unchanged = scale_pours_to_total(_pours(100), 0)
    assert [p["volume_ml"] for p in unchanged] == [100]


def test_inputs_not_mutated_and_fields_preserved():
    pours = [{"volume_ml": 100, "temperature_c": 92, "pattern": 1}]
    scaled = scale_pours_to_total(pours, 200)
    assert pours[0]["volume_ml"] == 100
    assert scaled[0]["volume_ml"] == 200
    assert scaled[0]["pattern"] == 1
