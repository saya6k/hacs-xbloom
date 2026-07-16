"""Tests for the firmware-version parsing/comparison helpers backing the
Firmware update entity and the Easy Mode / tea firmware gates.

Version numbers themselves are sourced from xBloom's own support docs
(Zendesk "xBloom Studio Firmware Update Summary" section, fetched
2026-07-16) — see coordinator.py's firmware-version block for the full
citation.
"""
from __future__ import annotations

from custom_components.xbloom.coordinator import (
    MIN_FIRMWARE_EASY_MODE,
    MIN_FIRMWARE_TEA,
    _firmware_at_least,
    _firmware_build,
)


def test_firmware_build_parses_known_versions():
    assert _firmware_build("V12.0D.122") == 122
    assert _firmware_build("V12.0D.210") == 210
    assert _firmware_build("V12.0D.300") == 300
    assert _firmware_build("V12.0D.500") == 500


def test_firmware_build_returns_none_for_blank_or_unrecognized():
    assert _firmware_build(None) is None
    assert _firmware_build("") is None
    assert _firmware_build("unknown") is None
    assert _firmware_build("V13.0D.100") is None  # a future scheme we don't parse


def test_firmware_at_least_orders_known_versions_correctly():
    assert _firmware_at_least("V12.0D.300", MIN_FIRMWARE_TEA)
    assert not _firmware_at_least("V12.0D.210", MIN_FIRMWARE_TEA)
    assert _firmware_at_least("V12.0D.210", MIN_FIRMWARE_EASY_MODE)
    assert not _firmware_at_least("V12.0D.122", MIN_FIRMWARE_EASY_MODE)


def test_firmware_at_least_fails_open_on_unknown_version():
    # No MachineInfo yet / unparseable string -> don't block a real feature
    # on a version string we can't read; let the machine's own behavior be
    # the final word.
    assert _firmware_at_least(None, MIN_FIRMWARE_TEA)
    assert _firmware_at_least("", MIN_FIRMWARE_TEA)
    assert _firmware_at_least("garbage", MIN_FIRMWARE_EASY_MODE)
