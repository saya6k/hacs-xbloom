"""Tests for _cloud_client._resolve_criteria_values (code-or-name matching)."""
from __future__ import annotations

from custom_components.xbloom._cloud_client import _resolve_criteria_values

FACET = [
    {"name": "Studio", "value": "J15"},
    {"name": "Original", "value": "J20"},
    {"name": "Catimor", "value": "26"},
    {"name": "Catimor", "value": "27"},
]


def test_name_match_case_insensitive():
    resolved, unmatched = _resolve_criteria_values(["studio"], FACET)
    assert resolved == ["J15"]
    assert unmatched == []


def test_code_match_wins_over_name():
    # "27" is a raw code — must resolve to itself, not via name lookup.
    resolved, unmatched = _resolve_criteria_values(["27", "J20"], FACET)
    assert resolved == ["27", "J20"]
    assert unmatched == []


def test_code_match_case_insensitive_resolves_to_live_casing():
    # services.yaml/strings.json option keys are lowercased ("j15") to
    # satisfy HA's translation-key rules, but the live API code is "J15" —
    # a lowercase submission must still resolve, and to the real casing.
    resolved, unmatched = _resolve_criteria_values(["j15", "j20"], FACET)
    assert resolved == ["J15", "J20"]
    assert unmatched == []


def test_unknown_reported_unmatched():
    resolved, unmatched = _resolve_criteria_values(["Mars"], FACET)
    assert resolved == []
    assert unmatched == ["Mars"]


def test_empty():
    assert _resolve_criteria_values(None, FACET) == ([], [])
    assert _resolve_criteria_values([], FACET) == ([], [])
