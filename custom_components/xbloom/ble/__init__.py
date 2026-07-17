"""Native XBloom Studio BLE implementation.

Per ADR-001 (../../adr/001-clean-room-reimplementation-of-xbloom-ble.md),
this package is a clean-room implementation of the BLE command table,
packet framing, and device state model — built from this integration's own
hardware findings and ``docs/en/protocol.md``, not by importing or patching
``custom_components/xbloom/src/xbloom`` (kept in the repo as an unmodified
reference/attribution copy only, matching ``src/xbloom-ble``'s existing
treatment).

The existing pytest suite is the compatibility oracle for this migration:
every test pinning previously hardware-confirmed wire behavior must keep
passing unmodified against this package.
"""
