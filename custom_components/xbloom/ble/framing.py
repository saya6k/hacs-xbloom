"""XBloom Studio BLE packet framing.

Native replacement for ``src/xbloom/protocol/builder.py``/``parser.py`` and
the framing loop previously duplicated between the vendored
``XBloomClient._on_notification`` and its override in ``_client.py``
(``_split_and_parse``). See ``docs/en/protocol.md`` for the wire-level
narrative this module implements.

Packet layout::

    header(0x58 0x02) | dev_id | type | cmd(2 LE) | len(4 LE) | const(0x01) | payload | crc(2)
"""
from __future__ import annotations

import struct
from typing import Iterator, List, Sequence

_HEADER_BYTES = (0x58, 0x02)
_DEFAULT_DEVICE_ID = 0x01
_DEFAULT_TYPE_CODE = 0x01

# Marker byte immediately after the length field (offset+9) on every real
# response frame. Empirically 0xC0 | type_code: type-1 responses carry
# 0xC1, type-2 responses carry 0xC2. A parser that only accepts 0xC1
# silently drops every type-2 response (this integration's own history —
# see docs/en/protocol.md).
TYPE1_MARKER_BYTE = 0xC1
TYPE2_MARKER_BYTE = 0xC2
_VALID_MARKER_BYTES = (TYPE1_MARKER_BYTE, TYPE2_MARKER_BYTE)

# Generous upper bound on a real XBloom packet. The weight/water-volume
# telemetry stream floods at multi-Hz, and a header byte can turn up by
# coincidence inside that noise; when it does, reading the next 4 bytes as
# a length field produces garbage (real captures have shown values like
# 3254779905). Real XBloom packets never approach this size, so anything
# past it is a false-positive header match: skip one byte and keep
# scanning instead of aborting the whole notification buffer.
MAX_PACKET_LEN = 256

# Max bytes per BLE write, matching the official Android app's fastble
# setSplitWriteNum(100): the app requests MTU 100 and splits every
# outbound packet into 100-byte chunks. The firmware reassembles a command
# from multiple writes (framing is header+length driven, not write-boundary
# driven), which matters for long payloads (recipe sends, Easy Slot writes)
# on low-MTU paths such as ESPHome BLE proxies.
SPLIT_WRITE_CHUNK_MAX = 100


def crc16(data: bytes) -> int:
    """CRC16 (polynomial 0x8408), matching the firmware's own checksum."""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0x8408
            else:
                crc >>= 1
    return crc


def build_packet(
    command: int,
    data: Sequence[int] | None = None,
    type_code: int = _DEFAULT_TYPE_CODE,
    device_id: int = _DEFAULT_DEVICE_ID,
) -> bytes:
    """Build an outbound packet from a list of 4-byte little-endian ints."""
    values = list(data) if data else []
    return build_packet_raw(
        command,
        b"".join(struct.pack("<I", v) for v in values),
        type_code=type_code,
        device_id=device_id,
    )


def build_packet_raw(
    command: int,
    data: bytes,
    type_code: int = _DEFAULT_TYPE_CODE,
    device_id: int = _DEFAULT_DEVICE_ID,
) -> bytes:
    """Build an outbound packet from a raw payload."""
    total_length = 12 + len(data)
    packet = bytearray()
    packet.append(0x58)
    packet.append(device_id)
    packet.append(type_code)
    packet.extend(struct.pack("<H", command))
    packet.extend(struct.pack("<I", total_length))
    packet.append(0x01)
    packet.extend(data)
    packet.extend(struct.pack("<H", crc16(bytes(packet))))
    return bytes(packet)


def iter_frames(raw_data: bytes) -> Iterator[bytes]:
    """Yield each complete, validated frame found in a BLE notification buffer.

    A single notification can carry more than one frame, a leading
    partial/unrelated frame, or (rarely) a coincidental header-byte match
    inside the flooding telemetry stream. This walks the whole buffer byte
    by byte for a real header, bounds the parsed length against
    ``MAX_PACKET_LEN``, and requires a valid marker byte — three
    independent checks that together make a false-positive match on pure
    noise vanishingly unlikely. A byte that fails any check is skipped
    (resync), not treated as a fatal parse error for the rest of the
    buffer.
    """
    offset = 0
    n = len(raw_data)
    while offset < n:
        if raw_data[offset] not in _HEADER_BYTES:
            offset += 1
            continue
        if n - offset < 10:
            break
        total_len = struct.unpack("<I", raw_data[offset + 5 : offset + 9])[0]
        if total_len > MAX_PACKET_LEN:
            offset += 1
            continue
        if raw_data[offset + 9] not in _VALID_MARKER_BYTES:
            offset += 1
            continue
        if offset + total_len > n:
            break
        yield raw_data[offset : offset + total_len]
        offset += total_len


def frame_command(frame: bytes) -> int:
    """Extract the command id (bytes 3-5, little-endian) from a frame."""
    return struct.unpack("<H", frame[3:5])[0]


def frame_payload(frame: bytes) -> bytes:
    """Extract the payload (after the 10-byte preamble, before the 2-byte CRC)."""
    return frame[10:-2] if len(frame) > 12 else b""


def split_write_chunks(data: bytes, mtu_size: int) -> List[bytes]:
    """Split an outbound packet into per-write chunks.

    Chunk size is ``min(100, mtu-3)`` with a floor of 20 (the BLE-minimum
    ATT_MTU of 23 minus the 3-byte write header) so a bogus/unknown
    ``mtu_size`` can never produce a zero or negative chunk.
    """
    chunk = max(20, min(SPLIT_WRITE_CHUNK_MAX, mtu_size - 3))
    return [data[i : i + chunk] for i in range(0, len(data), chunk)]
