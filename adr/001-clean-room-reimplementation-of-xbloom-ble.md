# ADR-001: Clean-room reimplementation of the XBloom BLE client

**Date**: 2026-07-17
**Status**: Accepted — amended 2026-07-18 (vendored reference copies removed; see Amendment below)

**Context**: This integration vendors two reverse-engineered upstreams —
[`fhenwood/PyBloom`](https://github.com/fhenwood/PyBloom) at `src/xbloom/`
and [`brAzzi64/xbloom-ble`](https://github.com/brAzzi64/xbloom-ble) at
`src/xbloom-ble/` — under a hard rule of "wrap or override, never modify."
`src/xbloom-ble` was never a runtime dependency (it has no `__init__.py`,
intentionally, and is treated as reference capture data). `src/xbloom`
started as a real, thin runtime dependency: `_client.py` subclassed its
`XBloomClient` and `coordinator.py` called into its `DeviceStatus`/
`GrinderController`/`BrewerController`.

Over roughly two months of hardware-driven bug fixes (firmware quirks,
undocumented commands found via APK decompilation, transport-timing bugs),
`_client.py` grew to override or bypass most of what `src/xbloom/core/
client.py` actually does: packet framing, marker-byte validation, connection
management, notification dispatch, state derivation, sleep tracking, and
mode-switch retry all now live in `_client.py` as overrides *on top of* a
vendored class whose own versions of that logic are mostly dead code at
runtime. Understanding any one quirk requires reading both the vendor's
original implementation and our override to know what actually executes —
the wrapper stopped being thin a long time ago, and the "never modify
vendor" rule no longer matches what the integration actually is.

**Options considered**:

1. Keep patching `src/xbloom` via subclassing/overrides in `_client.py`,
   as today.
2. Fork `src/xbloom` and maintain the fork directly.
3. Reimplement the BLE client natively in `custom_components/xbloom/`,
   clean-room (no code copied from the vendor), and stop importing
   `src/xbloom` at runtime — keeping the vendored tree checked in as an
   unmodified reference/attribution copy only, exactly as `src/xbloom-ble`
   is already treated.

**Decision**: Option 3. `custom_components/xbloom/ble/` becomes the native,
first-class implementation of connection management, packet framing, the
command table, and device state — built from this integration's own
hardware-verified findings and APK-decompile evidence, not by copying or
patching the vendor's source. `src/xbloom` and `src/xbloom-ble` both stay
checked in, byte-for-byte unmodified, as reference/attribution copies —
neither is imported by any runtime code once this migration completes.

**Rationale**:

- **The override-on-vendor pattern actively obscures behavior.** A reader
  has to reconstruct "vendor does X, but `_client.py` patches it to do Y"
  for nearly every piece of BLE logic in this integration. Owning the
  implementation outright makes the actual behavior legible in one place.
- **Maintenance**: this integration's protocol understanding has surpassed
  the vendor's in most areas that matter (see `docs/en/protocol.md`) —
  continuing to route through a base class we no longer trust for most of
  its own logic adds indirection without adding correctness.
- **Licensing stays clean**: no vendor source is copied into the native
  implementation, so there's no attribution entanglement beyond what
  already exists for the reference copies (see `docs/en/index.md`'s
  License section).
- **Precedent already exists**: `src/xbloom-ble` has been reference-only
  since this integration's early history. This extends the identical
  treatment to `src/xbloom`, rather than inventing a new policy.

**Consequences**:

- The existing pytest suite (`tests/`) is the compatibility oracle for this
  migration: every test that pins hardware-confirmed wire behavior
  (framing, marker bytes, event mapping, state derivation, etc.) must keep
  passing, unmodified, against the native implementation — that's the proof
  of parity, not a diff against the vendor's source.
- We own every bug in the BLE layer outright; there is no upstream to defer
  to for the parts we've reimplemented. (This was already effectively true
  for everything `_client.py` overrode — this ADR makes it official for the
  rest.)
- `src/xbloom`/`src/xbloom-ble` remain in the repo for attribution and as
  historical reference for anyone comparing our reimplementation against
  the original reverse-engineering work — they are documentation, not code,
  from this point on.
- Hard rule #1 in `AGENTS.md` is updated to describe this as the current
  state rather than "wrap or override."

## Amendment (2026-07-18): vendored reference copies removed

The original decision kept `src/xbloom` and `src/xbloom-ble` checked in as
byte-for-byte reference/attribution copies. With the native `ble/` package
fully established and nothing but a handful of tests still importing the
vendored `xbloom.*` package as a parity oracle, keeping ~440 KB of
never-imported source in-tree stopped earning its place. The two trees have
now been **deleted** from the repository.

What changes:

- **`custom_components/xbloom/src/` is gone.** The reverse-engineered
  upstreams are credited by link only — see the README's attribution and
  License sections for the repo URLs and each project's MIT license.
- **The parity tests no longer import the vendored package.** The three
  vendor-cross-check tests in `tests/test_ble_framing.py` and
  `tests/test_ble_models.py` were converted to **golden-vector** tests: the
  exact wire bytes were captured from the vendored oracle while it still
  existed, and are now frozen as hex literals in those tests. This preserves
  the byte-exact regression signal without the dependency.

What does **not** change: the native `ble/` package is still clean-room (no
vendor code was ever copied into it), so removing the reference copies has no
effect on the integration's own licensing. This amendment supersedes only the
"remain in the repo" consequence above; the decision to reimplement natively
stands unchanged.
