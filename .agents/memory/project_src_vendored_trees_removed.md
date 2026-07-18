---
name: project-src-vendored-trees-removed
description: The vendored src/xbloom and src/xbloom-ble reference copies were deleted 2026-07-18; older memories/comments citing src/xbloom* paths are stale.
metadata: 
  node_type: memory
  type: project
  originSessionId: 33a80524-3a0d-43b5-81e3-0b3d55205e70
---

On 2026-07-18 the vendored reference copies under
`custom_components/xbloom/src/` (`xbloom/` = fhenwood/PyBloom, `xbloom-ble/` =
brAzzi64/xbloom-ble, both MIT) were **deleted** from the repo. They had been
kept as byte-for-byte reference/attribution copies per ADR-001 but were never
imported at runtime and only 3 tests still used them as a parity oracle.

Changes made (all four requested steps):
1. The 3 vendor-cross-check tests in `tests/test_ble_framing.py` and
   `tests/test_ble_models.py` were converted to **golden-vector** tests
   (wire bytes captured from the vendored oracle while it still existed,
   frozen as hex literals). `tests/conftest.py` no longer puts the vendored
   path on sys.path. No code imports `xbloom.*` anymore.
2. ADR-001 got a dated **Amendment (2026-07-18)** section; AGENTS.md hard
   rule #1 rewritten to "clean-room native; upstreams removed, credited by
   link."
3. docs/en+ko `index.md` License sections rewritten (both upstreams MIT,
   credited by link, no vendored copy).
4. README attribution + License sections rewritten with the two repo URLs +
   MIT + "no upstream code copied into this repo's clean-room source."

**Why:** confirms `[[xbloom-original-j20-cloud-protocol]]`-era cleanup — the
native `ble/` package is self-sufficient. **How to apply:** any older memory
or source comment citing `src/xbloom/...` or `src/xbloom-ble/...` as an
in-repo path (e.g. `src/xbloom/core/client.py:NNN` in
[[xbloom-machineinfo-reliability-and-padding]], [[xbloom-removed-features]],
`brewing.py`/`ble/*.py` provenance comments) is now a **historical/upstream**
reference, not a live path — don't try to open those files; treat them as
"this native code mirrors upstream X." Do not re-add the vendored trees.
Related: [[project-llm-platform-migration-rc]].
