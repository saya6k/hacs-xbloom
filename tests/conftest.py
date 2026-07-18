"""Make the repo root importable so tests can import custom_components.xbloom.

Per ADR-001 (amended 2026-07-18) the vendored `custom_components/xbloom/src/`
reference copies have been removed and no test imports `xbloom.*` anymore —
the former parity tests now assert against frozen golden vectors instead —
so there is nothing but the repo root to put on sys.path.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
