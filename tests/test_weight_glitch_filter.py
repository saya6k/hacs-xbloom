"""Scale glitch filter (XBloomClient._filter_weight).

Mirrors AppJ15AutoManager.onCoffeeVolume exactly: a reading more than 300
units from the last accepted one is dropped, unless 4 consecutive readings
insist — a real step change (cup lifted, carafe swapped) — at which point
it is accepted and the counter resets. Same wire units as the app: both
sides read the identical float32 (WeightBleModel.intBitsToFloat).
"""
from __future__ import annotations

from custom_components.xbloom.ble.client import XBloomClient


def _client() -> XBloomClient:
    return XBloomClient(mac_address="AA:BB:CC:DD:EE:FF", connection=object())


def test_first_reading_is_always_accepted():
    client = _client()
    assert client._filter_weight(350.0) == 350.0


def test_small_changes_pass_through():
    client = _client()
    client._filter_weight(100.0)
    assert client._filter_weight(101.5) == 101.5
    assert client._filter_weight(399.9) == 399.9  # 298.4 delta, under limit


def test_single_glitch_is_held_at_the_last_good_value():
    client = _client()
    client._filter_weight(100.0)
    assert client._filter_weight(900.0) == 100.0  # spike rejected
    assert client._filter_weight(101.0) == 101.0  # stream recovers


def test_a_persistent_step_change_wins_on_the_fifth_reading():
    # A real step change (cup lifted off the scale) must not be filtered
    # forever. The app checks `outOfLimitCount >= 4` BEFORE incrementing,
    # so an outlier run is rejected exactly 4 times and accepted on the
    # 5th — pinned here so nobody "simplifies" it into an off-by-one.
    client = _client()
    client._filter_weight(400.0)
    for _ in range(4):
        assert client._filter_weight(0.0) == 400.0
    assert client._filter_weight(0.0) == 0.0  # 5th insists — accepted


def test_counter_resets_after_acceptance():
    client = _client()
    client._filter_weight(400.0)
    for _ in range(4):
        client._filter_weight(0.0)
    assert client._filter_weight(0.0) == 0.0
    # Filter is armed again from the new baseline.
    assert client._filter_weight(500.0) == 0.0


def test_counter_resets_on_an_in_range_reading():
    # Two outliers, then a normal reading — the outlier streak must not
    # carry over (the app zeroes outOfLimitCount on every acceptance).
    client = _client()
    client._filter_weight(100.0)
    client._filter_weight(900.0)
    client._filter_weight(900.0)
    client._filter_weight(100.0)
    assert client._filter_weight(900.0) == 100.0  # streak restarted


def test_wake_retry_matches_the_app():
    # AppBleManager resends while retryCount < 3, starting at 1 —
    # 3 total sends, and mode-switch rides the same mechanism.
    from custom_components.xbloom.coordinator.constants import (
        _MODE_SWITCH_MAX_ATTEMPTS,
        _WAKE_RETRY_MAX_ATTEMPTS,
    )

    assert _WAKE_RETRY_MAX_ATTEMPTS == 3
    assert _MODE_SWITCH_MAX_ATTEMPTS == 3
