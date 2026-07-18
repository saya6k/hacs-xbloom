"""Tests for the native ble/framing.py (see
adr/001-clean-room-reimplementation-of-xbloom-ble.md).

The build_packet/crc16 tests below pin byte-exact wire output against
*golden vectors* — hex strings captured from the former vendored src/xbloom
oracle at de-vendoring time, while it still existed to generate them. The
vendored tree has since been removed (it lived on only as a reference copy);
these frozen vectors are what remains of "the existing pytest suite is the
compatibility oracle" the ADR describes, and they still catch any drift in
the native framing.

Fuzz-style tests cover iter_frames' untrusted-input surface (the raw BLE
notification buffer) per the plan's probatio-inspired mandate: this parser
has already had two real bugs from telemetry noise (false-positive header
match, garbage length field) — see docs/en/protocol.md.
"""
from __future__ import annotations

import random
import struct

import pytest

from custom_components.xbloom.ble import framing


def test_crc16_matches_golden():
    golden = {
        b"": 0,
        b"\x00": 0,
        b"\x58\x01\x01\x19\x1f": 50138,
        bytes(range(64)): 26673,
    }
    for data, expected in golden.items():
        assert framing.crc16(data) == expected


@pytest.mark.parametrize(
    "command,data,type_code,device_id,expected",
    [
        (8100, [185, 1], 1, 1, "580101a41f1400000001b900000001000000bdd1"),
        (3500, [45, 90], 1, 1, "580101ac0d14000000012d0000005a0000008b38"),
        (40519, None, 1, 1, "580101479e0c00000001553e"),
        (11511, [1], 2, 1, "580102f72c100000000101000000918c"),
        (8002, [], 1, 3, "580301421f0c000000018554"),
    ],
)
def test_build_packet_matches_golden(command, data, type_code, device_id, expected):
    ours = framing.build_packet(command, data, type_code=type_code, device_id=device_id)
    assert ours.hex() == expected


@pytest.mark.parametrize(
    "command,data,type_code,expected",
    [
        (8004, b"\x01\x02\x03", 1, "580101441f0f0000000101020388ba"),
        (
            4513,
            bytes(range(20)),
            1,
            "580101a1112000000001000102030405060708090a0b0c0d0e0f10111213a317",
        ),
        (11510, b"", 1, "580101f62c0c00000001f33b"),
    ],
)
def test_build_packet_raw_matches_golden(command, data, type_code, expected):
    ours = framing.build_packet_raw(command, data, type_code=type_code)
    assert ours.hex() == expected


def _response_frame(
    cmd: int, payload: bytes = b"", marker: int = framing.TYPE1_MARKER_BYTE
) -> bytes:
    """Build a synthetic *inbound* response frame — distinct from
    build_packet/build_packet_raw, which build *outbound* commands and
    always carry the const(0x01) byte at offset 9, not a response marker.
    """
    total_len = 12 + len(payload)
    packet = bytearray()
    packet.append(0x58)
    packet.append(0x01)
    packet.append(0x01)
    packet.extend(struct.pack("<H", cmd))
    packet.extend(struct.pack("<I", total_len))
    packet.append(marker)
    packet.extend(payload)
    packet.extend(struct.pack("<H", framing.crc16(bytes(packet))))
    return bytes(packet)


def test_iter_frames_yields_single_frame():
    frame = _response_frame(40521, b"\xff" * 40)
    assert list(framing.iter_frames(frame)) == [frame]


def test_iter_frames_yields_multiple_concatenated_frames():
    a = _response_frame(40521, b"\xff" * 40)
    b = _response_frame(8105, struct.pack("<I", 42))
    assert list(framing.iter_frames(a + b)) == [a, b]


def test_iter_frames_accepts_type2_marker():
    frame = _response_frame(11511, b"\x01\x00\x00\x00", marker=framing.TYPE2_MARKER_BYTE)
    assert list(framing.iter_frames(frame)) == [frame]


def test_iter_frames_rejects_unknown_marker_byte():
    frame = _response_frame(8105, struct.pack("<I", 1), marker=0x00)
    assert list(framing.iter_frames(frame)) == []


def test_iter_frames_skips_garbage_length_field_from_noise():
    # A stray 0x58 inside telemetry noise, followed by 4 bytes that decode
    # to an enormous length — must not swallow the real frame that follows.
    noise = b"\x58" + bytes([0xC2, 0x00, 0x01, 0xFF]) + b"\x00\x01\x02\x03\x04"
    real = _response_frame(8105, struct.pack("<I", 42))
    assert list(framing.iter_frames(noise + real)) == [real]


def test_iter_frames_handles_partial_trailing_frame():
    full = _response_frame(8105, struct.pack("<I", 1))
    partial = full[:-3]
    assert list(framing.iter_frames(full + partial)) == [full]


def test_iter_frames_frame_command_and_payload_roundtrip():
    frame = _response_frame(8105, struct.pack("<I", 42))
    (parsed,) = list(framing.iter_frames(frame))
    assert framing.frame_command(parsed) == 8105
    assert struct.unpack("<I", framing.frame_payload(parsed)[:4])[0] == 42


@pytest.mark.parametrize("seed", range(25))
def test_iter_frames_never_raises_on_random_bytes(seed):
    rng = random.Random(seed)
    junk = bytes(rng.randrange(256) for _ in range(rng.randrange(0, 300)))
    # Must not raise, and every yielded frame must at least satisfy the
    # length/marker invariants iter_frames itself checks.
    for f in framing.iter_frames(junk):
        assert len(f) <= framing.MAX_PACKET_LEN
        assert f[9] in (framing.TYPE1_MARKER_BYTE, framing.TYPE2_MARKER_BYTE)


@pytest.mark.parametrize("seed", range(10))
def test_iter_frames_never_raises_on_truncated_real_frames(seed):
    rng = random.Random(seed)
    frame = _response_frame(8105, struct.pack("<I", rng.randrange(1000)))
    truncated = frame[: rng.randrange(0, len(frame))]
    assert list(framing.iter_frames(truncated)) == []


def test_split_write_chunks_normal_mtu():
    data = bytes(range(250))
    chunks = framing.split_write_chunks(data, mtu_size=185)
    assert b"".join(chunks) == data
    assert all(len(c) <= 100 for c in chunks)


def test_split_write_chunks_floor_on_tiny_mtu():
    data = bytes(range(50))
    chunks = framing.split_write_chunks(data, mtu_size=5)
    assert b"".join(chunks) == data
    assert all(len(c) <= 20 for c in chunks)
    assert all(len(c) > 0 for c in chunks)
