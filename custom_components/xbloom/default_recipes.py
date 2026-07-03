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
    # 옴니2 18g 약배v2 (light roast)
    # https://share-h5.xbloom.com/?id=KmMzhYCe5itq%2FJcqOLhiag%3D%3D
    # 1:8 ratio, 144 ml brew + bypass for hot (110 ml) / iced (25 ml)
    # ratio = 254 / 18 = 14.111111 (dose_g * ratio reproduces total_water)
    {
        "name": "약배전 핫",
        "grind_size": 57,
        "rpm": 60,
        "dose_g": 18.0,
        "ratio": 14.111111,
        "cup_type": "omni_dripper",
        "bypass_volume": 110.0,
        "bypass_temperature": 90.0,
        "pours": [
            {"volume_ml": 21, "temperature_c": 95, "pause_seconds": 0,  "flow_rate": 3.5, "pattern": "spiral", "vibration": "none"},
            {"volume_ml": 21, "temperature_c": 95, "pause_seconds": 14, "flow_rate": 3.5, "pattern": "spiral", "vibration": "after"},
            {"volume_ml": 52, "temperature_c": 95, "pause_seconds": 16, "flow_rate": 3.5, "pattern": "spiral", "vibration": "after"},
            {"volume_ml": 25, "temperature_c": 95, "pause_seconds": 20, "flow_rate": 3.0, "pattern": "spiral", "vibration": "none"},
            {"volume_ml": 25, "temperature_c": 93, "pause_seconds": 0,  "flow_rate": 3.0, "pattern": "spiral", "vibration": "none"},
        ],
    },
    {
        "name": "약배전 아이스",
        "grind_size": 57,
        "rpm": 60,
        "dose_g": 18.0,
        "ratio": 9.388889,
        "cup_type": "omni_dripper",
        "bypass_volume": 25.0,
        "bypass_temperature": 93.0,
        "pours": [
            {"volume_ml": 21, "temperature_c": 95, "pause_seconds": 0,  "flow_rate": 3.5, "pattern": "spiral", "vibration": "none"},
            {"volume_ml": 21, "temperature_c": 95, "pause_seconds": 14, "flow_rate": 3.5, "pattern": "spiral", "vibration": "after"},
            {"volume_ml": 52, "temperature_c": 95, "pause_seconds": 16, "flow_rate": 3.5, "pattern": "spiral", "vibration": "after"},
            {"volume_ml": 25, "temperature_c": 95, "pause_seconds": 20, "flow_rate": 3.0, "pattern": "spiral", "vibration": "none"},
            {"volume_ml": 25, "temperature_c": 93, "pause_seconds": 0,  "flow_rate": 3.0, "pattern": "spiral", "vibration": "none"},
        ],
    },
    # B75 옴니 18g 강배 (dark roast)
    # https://share-h5.xbloom.com/?id=Ruv07imSC5%2FIJNQ6pYY5mg%3D%3D
    # 1:8 ratio, 144 ml brew + bypass for hot (110 ml) / iced (25 ml)
    {
        "name": "강배전 핫",
        "grind_size": 57,
        "rpm": 60,
        "dose_g": 18.0,
        "ratio": 14.111111,
        "cup_type": "omni_dripper",
        "bypass_volume": 110.0,
        "bypass_temperature": 83.0,
        "pours": [
            {"volume_ml": 36, "temperature_c": 88, "pause_seconds": 40, "flow_rate": 3.0, "pattern": "spiral", "vibration": "after"},
            {"volume_ml": 72, "temperature_c": 86, "pause_seconds": 32, "flow_rate": 3.5, "pattern": "spiral", "vibration": "after"},
            {"volume_ml": 36, "temperature_c": 85, "pause_seconds": 16, "flow_rate": 3.5, "pattern": "spiral", "vibration": "none"},
        ],
    },
    {
        "name": "강배전 아이스",
        "grind_size": 57,
        "rpm": 60,
        "dose_g": 18.0,
        "ratio": 9.388889,
        "cup_type": "omni_dripper",
        "bypass_volume": 25.0,
        "bypass_temperature": 83.0,
        "pours": [
            {"volume_ml": 36, "temperature_c": 88, "pause_seconds": 40, "flow_rate": 3.0, "pattern": "spiral", "vibration": "after"},
            {"volume_ml": 72, "temperature_c": 86, "pause_seconds": 32, "flow_rate": 3.5, "pattern": "spiral", "vibration": "after"},
            {"volume_ml": 36, "temperature_c": 85, "pause_seconds": 16, "flow_rate": 3.5, "pattern": "spiral", "vibration": "none"},
        ],
    },
    # B75 20g 중약배 워시드 (medium-light washed)
    # 1:8 ratio, 160 ml brew + bypass for hot (120 ml) / iced (30 ml)
    {
        "name": "중약배전 워시드 핫",
        "grind_size": 57,
        "rpm": 60,
        "dose_g": 20.0,
        "ratio": 14.0,
        "cup_type": "omni_dripper",
        "bypass_volume": 120.0,
        "bypass_temperature": 92.0,
        "pours": [
            {"volume_ml": 21, "temperature_c": 100, "pause_seconds": 0,  "flow_rate": 3.5, "pattern": "spiral", "vibration": "none"},
            {"volume_ml": 21, "temperature_c": 95,  "pause_seconds": 15, "flow_rate": 3.5, "pattern": "spiral", "vibration": "after"},
            {"volume_ml": 58, "temperature_c": 95,  "pause_seconds": 15, "flow_rate": 3.5, "pattern": "spiral", "vibration": "after"},
            {"volume_ml": 30, "temperature_c": 94,  "pause_seconds": 20, "flow_rate": 3.0, "pattern": "spiral", "vibration": "none"},
            {"volume_ml": 58, "temperature_c": 93,  "pause_seconds": 0,  "flow_rate": 3.0, "pattern": "spiral", "vibration": "none"},
        ],
    },
    {
        "name": "중약배전 워시드 아이스",
        "grind_size": 57,
        "rpm": 60,
        "dose_g": 20.0,
        "ratio": 9.5,
        "cup_type": "omni_dripper",
        "bypass_volume": 30.0,
        "bypass_temperature": 92.0,
        "pours": [
            {"volume_ml": 36, "temperature_c": 88, "pause_seconds": 40, "flow_rate": 3.0, "pattern": "spiral", "vibration": "after"},
            {"volume_ml": 21, "temperature_c": 95, "pause_seconds": 15, "flow_rate": 3.5, "pattern": "spiral", "vibration": "after"},
            {"volume_ml": 58, "temperature_c": 95, "pause_seconds": 15, "flow_rate": 3.5, "pattern": "spiral", "vibration": "after"},
            {"volume_ml": 30, "temperature_c": 94, "pause_seconds": 20, "flow_rate": 3.0, "pattern": "spiral", "vibration": "none"},
            {"volume_ml": 58, "temperature_c": 93, "pause_seconds": 0,  "flow_rate": 3.0, "pattern": "spiral", "vibration": "none"},
        ],
    },
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
