"""HA-side brew orchestration.

Cherry-picks BLE sequences from ``src/xbloom-ble/python/xbloom.py``
(brAzzi64/xbloom-ble) without modifying either vendored upstream.

Coffee brews go through ``_async_brew_coffee`` (inline sequence) rather
than the vendored ``XBloomClient.brew`` / ``brew_without_grinding``,
because we need two things the vendored API doesn't expose:
  - an 8022 (Back to Home) prelude — without it a coffee brew after a
    previous tea brew (4513) falls back to a center pour instead of the
    recipe's pattern
  - real bypass values in the 8102 packet — the vendored path always
    hardcodes ``set_bypass(0.0, 0.0, dose)`` which silently drops the
    YAML's ``bypass_volume`` / ``bypass_temperature``

Tea (``cup_type=4``) uses the firmware's dedicated tea commands
``4513``/``4512`` because the standard 8004 path does NOT trigger tea
mode (verified locally 2026-05-28 — no tea UI, no siphon). A coffee brew
after a tea brew grinds normally as long as ``_async_brew_coffee`` sends
ONLY 8022 before the standard sequence — an earlier QUIT prelude here
(RECIPE_STOP + BREWER_QUIT + GRINDER_QUIT + RECIPE_START_QUIT) was the
cause of the "grinder skips after tea" bug and has been removed
(confirmed 2026-05-29; see docs/en/brewing-notes.md).

Tea BLE sequence:

    8022  Back to Home          — reset machine UI state
    8102  Set Bypass            — bypass off, dose=0 (no beans)
    8104  Set Cup               — tea bounds (200, 0)
    4513  APP_TEA_RECIP_CODE    — tea recipe payload (pattern=3 for
                                  steep separation, from AML225's
                                  cloud-API JSON schema)
    4512  APP_TEA_RECIP_MAKE    — execute the queued tea recipe
"""
from __future__ import annotations

import asyncio
import logging
import struct

from xbloom.models.recipes import build_recipe_payload
from xbloom.models.types import CupType, XBloomRecipe
from xbloom.protocol.constants import XBloomCommand

_LOGGER = logging.getLogger(__name__)

# Cherry-picked from src/xbloom-ble/python/xbloom.py CUP_TYPE_RANGES.
# Min is forced to 0.0 to match the safety-bypass pattern the vendored
# src/xbloom uses for the coffee cup types (see
# src/xbloom/core/client.py ``brew_without_grinding`` cup_bounds — the
# upstream PyBloom comment explains the 0 g telemetry issue that drives
# the bypass).
_TEA_CUP_BOUNDS = (200.0, 0.0)

# 8022 — RD_BackToHome. Constant lives in XBloomResponse in our vendored
# upstream because the HCI capture only confirmed inbound use, but the
# brAzzi64 capture shows the official app sends it outbound at brew
# start. Hardcoded here as an int to avoid coupling to either enum.
_CMD_BACK_TO_HOME = 8022

# 8500 — Scale tare/zero. Cherry-picked from
# src/xbloom-ble/python/xbloom.py (CMD_TARE).
_CMD_TARE = 8500

# 11510 — Easy Mode recipe send. Type-2 packet. See
# src/xbloom-ble/PROTOCOL.md "Easy Mode Slots — HCI Confirmed".
_CMD_EASY_RECIPE_SEND = 11510

# Easy Mode slot flag byte. Cherry-picked from
# src/xbloom-ble/python/xbloom.py (slot_flags / SLOT_GRINDER_*).
# Bit 4 (0x10) = scale ON; lower nibble = grinder (0x02 ON / 0x04 OFF).
_SLOT_GRINDER_OFF = 0x04
_SLOT_GRINDER_ON = 0x02
_SLOT_SCALE_BIT = 0x10

_SLOT_INDEX_BY_LETTER = {"A": 0, "B": 1, "C": 2}


def slot_flags(scale_on: bool, grinder_on: bool) -> int:
    """Mirrors src/xbloom-ble/python/xbloom.py:slot_flags()."""
    flags = _SLOT_GRINDER_ON if grinder_on else _SLOT_GRINDER_OFF
    if scale_on:
        flags |= _SLOT_SCALE_BIT
    return flags


# Pattern byte for tea substeps. The official iOS app uses pattern 1
# (circular) for tea steeps — the same enum as coffee — NOT the 3 we
# previously borrowed from AML225's cloud-API JSON. Confirmed by a
# PacketLogger capture of the official app (2026-05-28); the old
# pattern=3 hack did NOT prevent flattening. See docs/en/brewing-notes.md
# "Open — tea multi-steep flattens into one pour".
_TEA_PATTERN_BYTE = 1

# Sub-threshold cap (ml) for the tea pour volume sent over the wire. The Omni
# Tea Brewer's siphon fires at ~120 ml (160 ml capacity − leaf), draining
# instantly with no real soak. The official app sends a sub-threshold pour
# and the firmware auto-tops-up past the threshold AFTER the soak to trigger
# the drain (observed 2026-05-29: 90 ml pour → soak → ~34 ml auto top-up →
# drain). So we cap the wire pour below the threshold and let the firmware do
# the top-up; the recipe keeps its authored volume. 90 ml is safely below the
# ~100-110 ml threshold for 5 g leaf. Heuristic — not the app's exact
# per-steep value (see docs/en/brewing-notes.md).
_TEA_SIPHON_CAP = 90


def _build_tea_payload(recipe: XBloomRecipe) -> bytes:
    """Tea recipe payload aligned to the official app's 4513 encoding.

    Per the 2026-05-28 PacketLogger capture a tea steep is a
    ``[substep][timing]`` pair (same layout as coffee's
    ``build_recipe_payload``) with three tea-specific differences that
    keep the firmware from flattening multi-steep recipes into one pour
    (``316 ml = 120 + 76 + 120`` — without a recognised steep boundary the
    firmware misreads the timing pause byte as another volume):

      - the pour volume is capped at ``_TEA_SIPHON_CAP`` (90 ml) so the
        firmware soaks then auto-tops-up to drain; the recipe keeps its
        authored volume
      - substep pattern byte = 1 (circular), not the old pattern=3 hack
      - the timing block carries the soak time in byte[1] (nonzero) —
        coffee leaves byte[1] = 0; this nonzero byte is the apparent
        steep-separation marker. byte[0] (inter-pour wait) is 0.
      - footer is ``[grind_size, ratio×10]`` (mirrors ``encode_recipe``),
        not ``[grind_size, total_water×10]``

    Steep separation is confirmed working on hardware (2026-05-29) — the
    pattern 3→1 change was the fix. The soak time is written to byte[1]
    as a positive value scaled by 0.6: the firmware runs the idle wait at
    ~1.67× the byte, so 0.6×`pausing` makes the actual wait ≈ the recipe's
    seconds. The 0.6 scale is approximate (two coarse stopwatch points) —
    see brewing-notes.
    """
    parts: list[bytes] = []
    for i, pour in enumerate(recipe.pours):
        # Cap the wire pour below the siphon threshold; the firmware tops up
        # to drain after the soak. The recipe keeps its authored volume.
        remaining = min(pour.volume, _TEA_SIPHON_CAP)
        while remaining > 127:
            parts.append(struct.pack(
                "BBBB", 127, pour.temperature,
                _TEA_PATTERN_BYTE, int(pour.vibration),
            ))
            remaining -= 127
        if remaining > 0:
            parts.append(struct.pack(
                "BBBB", remaining, pour.temperature,
                _TEA_PATTERN_BYTE, int(pour.vibration),
            ))
        # Timing block: [inter_pour_wait, soak, rpm, flow]. The soak goes
        # in byte[1] (nonzero = steep boundary); byte[0] stays 0 — our
        # recipes have no separate inter-pour wait. Hardware calibration
        # (2026-05-29): the firmware reads byte[1] as a POSITIVE value and
        # runs the idle wait at ~1.67× it (byte 180 → ~300 s, 120 → ~180 s),
        # so scale `pausing` by 0.6 to make the actual wait ≈ the recipe's
        # seconds. Kept ≥1 so the byte stays nonzero (steep marker) and
        # clamped to 255. Scale is approximate — see brewing-notes.
        soak_byte = max(1, min(round(pour.pausing * 0.6), 255))
        flow_byte = int(pour.flow_rate * 10) & 0xFF
        rpm_byte = (recipe.rpm & 0xFF) if i == 0 else 0
        parts.append(struct.pack("BBBB", 0, soak_byte, rpm_byte, flow_byte))

    body = b"".join(parts)
    grind_byte = recipe.grind_size & 0xFF
    dose = int(recipe.bean_weight)
    ratio_byte = (int(recipe.total_water / dose * 10) & 0xFF) if dose > 0 else 0
    footer = struct.pack("BB", grind_byte, ratio_byte)
    return struct.pack("B", len(body)) + body + footer


def _build_coffee_recipe_payload(recipe: XBloomRecipe) -> bytes:
    """Build a recipe blob whose footer matches brAzzi64's ``encode_recipe``.

    The vendored ``build_recipe_payload`` writes ``total_water * 10`` as
    footer byte 2, but the machine expects ``ratio * 10`` (ratio =
    total_water / dose).  This is confirmed by the decompiled official app
    (``RecipeDetailActivity`` line 670: ``dose × grandWater ==
    totalPourVolume``) and every HCI capture in brAzzi64's PROTOCOL.md.

    In live brew the dose arrives via the separate ``8102`` command, so
    the wrong footer byte is sometimes tolerated.  In Easy Mode the
    machine must derive the dose from the stored recipe blob — if the
    footer encodes ``total_water * 10`` instead of ``ratio * 10`` the
    machine computes the wrong dose and may skip grinding entirely (hot
    water only).

    Body encoding (substep chunking, timing blocks, length byte) is
    identical to the vendored builder — only the footer byte 2 correction
    is applied.
    """
    # Reuse the vendored builder for the body; only the footer needs
    # correcting.
    vendored = build_recipe_payload(recipe)
    body_content = vendored[1:-2]  # strip length byte + [grind_byte, water_byte]

    grind_byte = recipe.grind_size & 0xFF
    total_water = sum(p.volume for p in recipe.pours)
    dose = recipe.bean_weight
    ratio = (total_water / dose) if dose > 0 else 0
    ratio_byte = int(ratio * 10) & 0xFF

    body_len = len(body_content)
    footer = struct.pack("BB", grind_byte, ratio_byte)
    return struct.pack("B", body_len) + body_content + footer


def _cup_value(recipe: XBloomRecipe) -> int:
    cup = recipe.cup_type
    return int(cup.value if hasattr(cup, "value") else cup)


def is_tea_recipe(recipe: XBloomRecipe) -> bool:
    return _cup_value(recipe) == int(CupType.TEA)


# Cup bounds for coffee brews. Two tables match the vendored
# ``XBloomClient.brew`` / ``brew_without_grinding`` values — the no-grind
# variant uses min=0 to bypass the 0 g telemetry safety check that the
# upstream PyBloom comment documents.
_COFFEE_CUP_BOUNDS_GRIND = {1: (80.0, 40.0), 2: (90.0, 40.0), 3: (90.0, 40.0)}
_COFFEE_CUP_BOUNDS_NO_GRIND = {1: (80.0, 0.0), 2: (90.0, 0.0), 3: (90.0, 0.0)}
_COFFEE_CUP_BOUNDS_DEFAULT = (90.0, 40.0)


async def async_execute_recipe(
    client,
    recipe: XBloomRecipe,
    *,
    bypass_volume: float = 0.0,
    bypass_temperature: float = 0.0,
) -> None:
    """Route a recipe to the correct BLE flow.

    Tea recipes take the cherry-picked sequence in ``_async_brew_tea``.
    Coffee recipes go through ``_async_brew_coffee``, which mirrors the
    vendored ``XBloomClient.brew`` sequence but adds an 8022 reset prelude
    (matches brAzzi64/xbloom-ble) and threads ``bypass_volume`` /
    ``bypass_temperature`` from the YAML into the 8102 packet — the
    vendored path always hardcoded those to zero.
    """
    if is_tea_recipe(recipe):
        await _async_brew_tea(client, recipe)
        return
    await _async_brew_coffee(
        client, recipe,
        bypass_volume=bypass_volume,
        bypass_temperature=bypass_temperature,
    )


async def _async_brew_coffee(
    client,
    recipe: XBloomRecipe,
    *,
    bypass_volume: float = 0.0,
    bypass_temperature: float = 0.0,
) -> None:
    """Coffee brew sequence with optional bypass support.

    Mirrors ``send_brew_packets`` from brAzzi64/xbloom-ble plus the
    grind/no-grind cup-bound split from the vendored ``XBloomClient``.
    Bypass values come from the YAML's ``bypass_volume`` /
    ``bypass_temperature`` (0 = bypass disabled).
    """
    if not client.is_connected:
        raise ConnectionError("XBloom not connected")

    grinding = recipe.grind_size > 0 and recipe.bean_weight > 0
    dose = int(recipe.bean_weight) if grinding else 0

    _LOGGER.info(
        "Coffee brew start: %s (grind=%s, dose=%dg, bypass=%.0fml@%.0f°C)",
        recipe.name, grinding, dose, bypass_volume, bypass_temperature,
    )

    # 1.0 s spacing — matches the existing vendored ``XBloomClient.brew``
    # cadence that has worked in the field. brAzzi64 uses 2.0 s but the
    # tighter spacing has never dropped packets on the coffee path.
    _STEP_DELAY = 1.0

    # ── Reset prelude ───────────────────────────────────────────────────
    # 8022 (Back to Home) only. A PacketLogger capture of the official app
    # going tea→coffee (2026-05-28) showed it sends NO mode-exit commands —
    # just BYPASS/CUP/AUTO/EXECUTE — and grinds fine on the first coffee after
    # a tea brew. An earlier QUIT prelude here (RECIPE_STOP + BREWER_QUIT +
    # GRINDER_QUIT + RECIPE_START_QUIT) turned out to be the CAUSE of the
    # "grinder skips after tea" bug, not a cure; removing it restored grinding
    # after tea (confirmed 2026-05-29: grind + spiral pour + temperature +
    # vibration all correct). 8022 is kept — it independently restores
    # pour-pattern interpretation, so it stays.
    await client._send_command(_CMD_BACK_TO_HOME)
    await asyncio.sleep(_STEP_DELAY)

    # 8102 — Bypass + dose. The dose byte is REQUIRED for the grinder
    # (vendored comment: "Even when bypass water is disabled, dose MUST
    # be set!"). Non-zero ``bypass_volume`` / ``bypass_temperature``
    # enable the post-brew bypass dispense.
    await client.set_bypass(bypass_volume, bypass_temperature, dose)
    await asyncio.sleep(_STEP_DELAY)

    # 8104 — Cup bounds. Grind path uses min=40; no-grind path uses
    # min=0 to bypass the 0 g telemetry safety check.
    bounds_table = _COFFEE_CUP_BOUNDS_GRIND if grinding else _COFFEE_CUP_BOUNDS_NO_GRIND
    cup_max, cup_min = bounds_table.get(_cup_value(recipe), _COFFEE_CUP_BOUNDS_DEFAULT)
    await client.set_cup(cup_max, cup_min)
    await asyncio.sleep(_STEP_DELAY)

    # Recipe: 8001 (APP_RECIPE_SEND_AUTO, with grinding) or 8004
    # (APP_RECIPE_SEND_MANUAL, no grinding).
    payload = _build_coffee_recipe_payload(recipe)
    recipe_cmd = (
        XBloomCommand.APP_RECIPE_SEND_AUTO if grinding
        else XBloomCommand.APP_RECIPE_SEND_MANUAL
    )
    await client._send_command_raw(recipe_cmd, payload)
    await asyncio.sleep(_STEP_DELAY)

    # 8002 — Execute.
    await client.execute_coffee_recipe()


async def _async_brew_tea(client, recipe: XBloomRecipe) -> None:
    """Send the tea brew sequence over an already-connected client."""
    if not client.is_connected:
        raise ConnectionError("XBloom not connected")

    _LOGGER.info(
        "Tea brew start: %s — %d steep(s)", recipe.name, len(recipe.pours),
    )

    # Spacing between brew packets. brAzzi64's send_brew_packets uses
    # 2.0 s; with 0.3 s the firmware ACK'd only the first command and
    # silently dropped the rest (see log analysis 2026-05-13).
    _STEP_DELAY = 2.0

    # 8022 — Back to Home. Cleanly resets any lingering recipe / scale
    # screen state on the machine before we start a new sequence.
    await client._send_command(_CMD_BACK_TO_HOME)
    await asyncio.sleep(_STEP_DELAY)

    # 8102 — Bypass off, dose=0. Tea has no weighed bean dose; sending
    # this still tells the firmware "no grinder, no bypass".
    await client.set_bypass(0.0, 0.0, 0)
    await asyncio.sleep(_STEP_DELAY)

    # 8104 — Cup bounds for tea (200, 0). brAzzi64 reports the firmware
    # tolerates any value here, but matching the cloud-API tea defaults
    # avoids any chance of a scale-overflow guard tripping.
    cup_max, cup_min = _TEA_CUP_BOUNDS
    await client.set_cup(cup_max, cup_min)
    await asyncio.sleep(_STEP_DELAY)

    # 4513 — APP_TEA_RECIP_CODE. The ONLY known way to actually trigger
    # tea mode on the firmware (tea-cup UI icon, soak timer, internal
    # siphon-drain). Verified 2026-05-28: the standard 8004 path with
    # tea cup bounds (200, 0) was tested and the firmware did NOT enter
    # tea mode — it just brewed as no-grind multi-pour coffee. So
    # 4513/4512 is mandatory for real tea behavior.
    #
    # The downside: 4513/4512 puts the firmware in a tea state that no
    # documented command exits. The coffee-brew prelude in
    # ``_async_brew_coffee`` (RECIPE_STOP + BREWER_QUIT + GRINDER_QUIT
    # + RECIPE_START_QUIT + BACK_TO_HOME) is the current attempt to
    # clear it before subsequent coffee brews.
    #
    # ``_build_tea_payload`` substitutes pattern=3 in the substep byte
    # (AML225's cloud-API JSON schema uses that value for every tea
    # steep). Without it the firmware flattens multi-pour tea into a
    # single coffee-style pour.
    payload = _build_tea_payload(recipe)
    await client._send_command_raw(
        XBloomCommand.APP_TEA_RECIP_CODE, payload,
    )
    await asyncio.sleep(_STEP_DELAY)

    # 4512 — APP_TEA_RECIP_MAKE. Execute. The vendored
    # ``XBloomClient.execute_recipe`` re-sends the payload here rather
    # than an empty execute; we mirror that.
    await client._send_command_raw(
        XBloomCommand.APP_TEA_RECIP_MAKE, payload,
    )


async def async_tare(client) -> None:
    """Zero the scale (cmd 8500).

    Mirrors ``send_command.py tare`` in src/xbloom-ble. No payload.
    """
    if not client.is_connected:
        raise ConnectionError("XBloom not connected")
    _LOGGER.info("Scale tare")
    await client._send_command(_CMD_TARE)


async def async_write_easy_slot(
    client,
    slot_letter: str,
    recipe: XBloomRecipe,
    *,
    scale_on: bool = True,
) -> None:
    """Write a recipe to Easy Mode slot A/B/C (cmd 11510, type-2).

    Mirrors ``send_command.py slot`` plus
    ``build_slot_packet`` / ``slot_flags`` in src/xbloom-ble. The
    ``grinder_on`` flag is derived from the recipe (any positive
    grind_size + bean_weight implies the slot should grind).

    Payload layout (after the header / type / cmd / len / 0x01 prefix
    that build_command_raw applies): ``[slot_index][flags][recipe_hex]``.
    """
    if not client.is_connected:
        raise ConnectionError("XBloom not connected")
    letter = slot_letter.strip().upper()
    if letter not in _SLOT_INDEX_BY_LETTER:
        raise ValueError(f"slot must be A, B, or C — got {slot_letter!r}")
    slot_index = _SLOT_INDEX_BY_LETTER[letter]

    grinder_on = recipe.grind_size > 0 and recipe.bean_weight > 0
    flags = slot_flags(scale_on, grinder_on)

    recipe_blob = _build_coffee_recipe_payload(recipe)
    payload = bytes([slot_index, flags]) + recipe_blob

    _LOGGER.info(
        "Easy slot write: %s ← %s (grinder=%s scale=%s, %d-byte recipe)",
        letter, recipe.name, grinder_on, scale_on, len(recipe_blob),
    )
    # Type-2 packet: brAzzi64 build_packet_type2(11510, hex_data). Our
    # vendored build_command_raw produces the same bytes when type_code=2.
    await client._send_command_raw(
        _CMD_EASY_RECIPE_SEND, payload, type_code=2,
    )
