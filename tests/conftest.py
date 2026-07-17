"""Make the repo root importable so tests can import custom_components.xbloom.

Also puts the vendored reference copy (custom_components/xbloom/src/) on
sys.path — test-only, per ADR-001: production code no longer imports
xbloom.* at runtime, but a handful of tests still import it directly as a
parity oracle (proving the native ble/ package is byte-exact with the
vendored implementation it replaces).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_VENDOR_PATH = REPO_ROOT / "custom_components" / "xbloom" / "src"
if str(_VENDOR_PATH) not in sys.path:
    sys.path.insert(0, str(_VENDOR_PATH))
