"""Two-phase arm/confirm flow for the grind/pour LLM tools + cancel tool
(T12 / SPEC F).

The first call (confirmed absent/false) ARMS the machine — it enters the
standalone page with the requested settings, so it is already showing
what will happen while the agent asks the user to confirm. The second
call with confirmed=true starts it. Declining routes to the new
xbloom__cancel tool, which backs out of armed screens.

Source-level pins (the llm modules import Home Assistant, unavailable in
the pure-logic test env) — the same approach as the llm-platform
invariant tests.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parent.parent / "custom_components" / "xbloom"


def _src(rel: str) -> str:
    return (ROOT / rel).read_text()


def test_grind_tool_is_two_phase():
    src = _src("llm/grind.py")
    assert '"confirmed"' in src
    assert "async_arm_grind" in src
    assert "async_confirm_grind" in src
    # No one-shot start: confirmed=true without a standing arm re-arms.
    assert "async_grind()" not in src


def test_pour_tool_is_two_phase():
    src = _src("llm/pour.py")
    assert '"confirmed"' in src
    assert "async_arm_pour" in src
    assert "async_confirm_pour" in src
    assert "async_pour()" not in src


def test_pour_boiling_maps_to_the_bp_slider_endpoint():
    """boiling=true must set the mirrored setpoint to the BP endpoint
    (96 — transmits 98), not a raw 100 that overflows the 39-96 slider."""
    src = _src("llm/pour.py")
    assert "TEMPERATURE_BOILING_C = 96" in src


def test_cancel_tool_exists_and_is_registered():
    src = _src("llm/cancel.py")
    assert 'name = "xbloom__cancel"' in src
    assert "async_cancel" in src
    catalog = _src("llm/catalog.py")
    assert "XBloomCancelTool" in catalog


def test_tool_descriptions_document_the_flow():
    for rel in ("llm/grind.py", "llm/pour.py"):
        src = _src(rel)
        assert "confirmed=true" in src, rel
        assert "xbloom__cancel" in src, rel


def test_prompt_mentions_cancel_and_two_phase():
    tree = ast.parse(_src("const.py"))
    prompt = None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "XBLOOM_LLM_PROMPT"
        ):
            prompt = ast.literal_eval(node.value)
    assert prompt is not None
    assert "xbloom__cancel" in prompt
    assert "confirmed=true" in prompt
