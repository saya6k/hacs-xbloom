"""Native XBloom Studio BLE implementation.

Per ADR-001 (../../adr/001-clean-room-reimplementation-of-xbloom-ble.md),
this package is a clean-room implementation of the BLE command table,
packet framing, and device state model — built from this integration's own
hardware findings and ``docs/en/protocol.md``, not by importing or patching
the reverse-engineered upstreams (``fhenwood/PyBloom``, ``brAzzi64/xbloom-ble``)
it originally replaced. Those upstreams were once vendored under
``custom_components/xbloom/src/`` as reference copies; they have since been
removed and are credited by link only (see README).

The pytest suite is the compatibility oracle for this package: the framing
and recipe tests pin previously hardware-confirmed wire output against
golden vectors captured from the vendored oracle before it was removed
(see ``tests/test_ble_framing.py``).
"""
