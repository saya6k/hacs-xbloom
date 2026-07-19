"""The coffee recipe footer's ratio byte must never round DOWN.

Root-caused on hardware 2026-07-19 after three water-only brews: the firmware
reconstructs the expected total water as dose × ratio_byte/10, and when that
lands below the pours' actual sum it silently downgrades the brew to no-grind
— 8001 is ACKed, the pours run, the grinder never starts, no error. The old
``int()`` truncation produced exactly that for any dose/volume pair whose
ratio isn't a clean multiple of 0.1 (18g/250ml → 138 → 248.4 < 250). A byte
one high (139 → 250.2) and two high (140 → 252) both grind, so ceil's
bounded overshoot (< 0.1 × dose) is tolerated while any undershoot is fatal.
"""
from __future__ import annotations

from custom_components.xbloom.ble.models import CupType, PourStep, XBloomRecipe
from custom_components.xbloom.brewing import _build_coffee_recipe_payload


def _recipe(dose: float, volumes: list[int]) -> XBloomRecipe:
    return XBloomRecipe(
        name="ratio", grind_size=35, rpm=90, cup_type=int(CupType.OMNI_DRIPPER),
        bean_weight=dose,
        pours=[PourStep(volume=v, temperature=93) for v in volumes],
    )


def _ratio_byte(recipe: XBloomRecipe) -> int:
    return _build_coffee_recipe_payload(recipe)[-1]


def test_inexact_ratio_rounds_up_never_down():
    # 250/18 = 13.888… — truncation gave 138 and the machine never ground.
    assert _ratio_byte(_recipe(18.0, [250])) == 139


def test_exact_ratio_is_unchanged():
    # 225/15 = 15.0 exactly — no overshoot is introduced.
    assert _ratio_byte(_recipe(15.0, [225])) == 150


def test_reconstructed_total_never_undershoots_the_pour_sum():
    # The property the firmware actually enforces, across a spread of
    # dose/volume combinations whose ratio the wire byte can express
    # (ratio ≤ 25.5).
    for dose in (10.0, 12.5, 15.0, 16.0, 18.0):
        for total in (150, 200, 225, 250, 252, 300):
            if total / dose > 25.5:
                continue
            byte = _ratio_byte(_recipe(dose, [min(total, 127), total - min(total, 127)] if total > 127 else [total]))
            assert dose * byte / 10 >= total - 1e-9, (
                f"dose={dose} total={total}: byte {byte} reconstructs "
                f"{dose * byte / 10:.1f}ml < {total}ml — machine would not grind"
            )


def test_extreme_ratio_clamps_instead_of_wrapping():
    # 300/10 = ratio 30 → 300 doesn't fit a byte. & 0xFF used to alias it
    # to 44 (reconstructing 44ml), guaranteeing the no-grind downgrade;
    # 255 is the closest the wire format can express.
    assert _ratio_byte(_recipe(10.0, [127, 173])) == 255


def test_zero_dose_keeps_zero_ratio():
    # No-grind recipes (dose 0) don't have a meaningful ratio.
    recipe = XBloomRecipe(
        name="no-grind", grind_size=0, rpm=0, cup_type=int(CupType.OMNI_DRIPPER),
        bean_weight=0.0, pours=[PourStep(volume=100, temperature=93)],
    )
    assert _build_coffee_recipe_payload(recipe)[-1] == 0
