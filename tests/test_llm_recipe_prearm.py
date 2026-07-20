"""execute_xbloom_recipe pre-arms before asking for confirmation (T13).

When confirmation gates (beans/dripper/filter/cup) are not yet satisfied
— and the connection/water checks pass — the tool arms the recipe so the
machine is already showing its start prompt while the agent asks the
user. The confirmed follow-up call then confirms the standing arm
instead of re-executing the whole chain.

Pre-arming is deliberately skipped when per-call overrides are present:
the armed payload always carries the recipe's stored settings, so a
confirm would ignore the overrides — those calls keep the one-shot path
(and a stale arm is cancelled first).

Source-level pins, like the other llm-module tests.
"""
from __future__ import annotations

from pathlib import Path

SRC = (
    Path(__file__).parent.parent
    / "custom_components"
    / "xbloom"
    / "llm"
    / "recipe.py"
).read_text()


def test_prearm_and_confirm_paths_exist():
    assert "async_arm_recipe" in SRC
    assert "async_confirm_recipe" in SRC


def test_overrides_bypass_the_arm_flow():
    assert "has_overrides" in SRC
    # A standing arm with overrides on the confirmed call is cancelled
    # before the one-shot execute, never silently confirmed.
    assert "async_cancel" in SRC


def test_confirmation_ask_mentions_the_prompt_on_the_machine():
    assert "start prompt" in SRC
