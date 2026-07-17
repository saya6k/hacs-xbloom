"""Tests for _client._split_write_chunks (outbound BLE write splitting).

Mirrors the official Android app's fastble setSplitWriteNum(100): every
outbound packet is written in chunks of at most 100 bytes, additionally
bounded by the negotiated MTU's write-without-response payload limit
(mtu - 3). The firmware reassembles commands from the notification-style
header+length framing, so chunk boundaries mid-packet are fine — the app
does exactly this for every write.
"""
from __future__ import annotations

from custom_components.xbloom._client import _SPLIT_WRITE_CHUNK_MAX, _split_write_chunks


def test_short_packet_is_a_single_chunk():
    data = bytes(range(12))
    assert _split_write_chunks(data, 517) == [data]


def test_exact_chunk_boundary_is_a_single_chunk():
    data = bytes(_SPLIT_WRITE_CHUNK_MAX)
    assert _split_write_chunks(data, 517) == [data]


def test_long_packet_splits_at_100_on_a_large_mtu():
    data = bytes(250)
    chunks = _split_write_chunks(data, 517)
    assert [len(c) for c in chunks] == [100, 100, 50]
    assert b"".join(chunks) == data


def test_low_mtu_bounds_the_chunk_below_100():
    # e.g. an ESPHome proxy path that only negotiated MTU 63 → 60-byte chunks
    data = bytes(130)
    chunks = _split_write_chunks(data, 63)
    assert [len(c) for c in chunks] == [60, 60, 10]
    assert b"".join(chunks) == data


def test_minimum_mtu_floors_the_chunk_at_20():
    # ATT minimum MTU is 23 → 20-byte payload; a bogus smaller value must
    # not produce a zero/negative chunk size.
    data = bytes(45)
    for mtu in (23, 0, -1):
        chunks = _split_write_chunks(data, mtu)
        assert [len(c) for c in chunks] == [20, 20, 5]
        assert b"".join(chunks) == data
