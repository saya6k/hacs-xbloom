"""Recipes shipped with the integration.

These appear in ``coordinator.recipes`` automatically on first setup so
users see something useful before adding their own. Defaults are
read-only from the OptionsFlow — to override one, add a same-named
recipe in ``configuration.yaml`` (YAML wins) or via OptionsFlow
``Add a recipe`` (options wins).

Each entry must pass ``schema.RECIPE_SCHEMA``. Tested at import time
by ``__init__.py`` via the same schema.
"""
from __future__ import annotations

DEFAULT_RECIPES: list[dict] = [
    # ── Coffee ───────────────────────────────────────────────────────
    # Intentionally empty. coordinator.async_seed_recipes() backgrounds a
    # live search for real xBloom Official recipes (cup_type="Omni" only —
    # see its call site) on first setup instead of shipping a hand-picked,
    # inevitably-stale static list here. Previously held 6 personal
    # (non-official) coffee recipes; removed per an explicit "bundled
    # defaults should be real xBloom Official recipes, kept current via
    # search rather than hardcoded" requirement (2026-07-16).
    #
    # ── Tea (cup_type=tea) ───────────────────────────────────────────
    # dose_g=0 (no weighed leaf dose tracked) — ratio is omitted and
    # total water is derived from the sum of pour volumes instead (see
    # schema.compute_total_water_ml). Both entries below sum to the same
    # total_water the pre-rename schema stored explicitly (240 ml).
    # 1. Hibiscus berry herbal tea (Pepperpot Tea Co.) — xBloom official
    #    https://xbloom.com/products/pepperpot-tea-hibiscus-berry
    {
        "name": "히비스커스 베리",
        "cup_type": "tea",
        "grind_size": 0,
        "rpm": 0,
        "dose_g": 0.0,
        "pours": [
            {"volume_ml": 120, "temperature_c": 100, "pause_seconds": 300},
            {"volume_ml": 120, "temperature_c": 100, "pause_seconds": 120},
        ],
    },
    # 2. China Breakfast black tea (Passenger Coffee & Tea)
    #    https://xbloom.com/products/china-breakfast
    {
        "name": "홍차",
        "cup_type": "tea",
        "grind_size": 0,
        "rpm": 0,
        "dose_g": 0.0,
        "pours": [
            {"volume_ml": 120, "temperature_c": 95, "pause_seconds": 180},
            {"volume_ml": 120, "temperature_c": 95, "pause_seconds": 120},
        ],
    },
    # 3. Liang Family Long Jing #43 green tea (Passenger Coffee & Tea)
    #    https://xbloom.com/products/liang-family-green-tea
    {
        "name": "녹차",
        "cup_type": "tea",
        "grind_size": 0,
        "rpm": 0,
        "dose_g": 0.0,
        "pours": [
            {"volume_ml": 120, "temperature_c": 80, "pause_seconds": 120},
            {"volume_ml": 120, "temperature_c": 80, "pause_seconds": 60},
        ],
    },
    # 4. Hibiscus iced tea (xBloom official — same brew as Hibiscus
    #    Berry above; user pre-loads 100 g of ice in the cup)
    {
        "name": "히비스커스 아이스티",
        "cup_type": "tea",
        "grind_size": 0,
        "rpm": 0,
        "dose_g": 0.0,
        "pours": [
            {"volume_ml": 120, "temperature_c": 100, "pause_seconds": 300},
            {"volume_ml": 120, "temperature_c": 100, "pause_seconds": 120},
        ],
    },
]
