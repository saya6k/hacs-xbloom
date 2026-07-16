"""XBLOOM_LLM_PROMPT must describe the current tool surface (SPEC §5).

Mirrors the tool list in llm/catalog.py (build_tools) — update both together
when a tool is added/removed/renamed; test_registered_tools_match_catalog
enforces the mirror.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.xbloom.const import XBLOOM_LLM_PROMPT

REGISTERED_TOOLS = (
    "get_xbloom_status",
    "list_xbloom_recipes",
    "get_xbloom_recipe",
    "create_xbloom_recipe",
    "edit_xbloom_recipe",
    "delete_xbloom_recipe",
    "pour_xbloom",
    "execute_xbloom_recipe",
    "write_xbloom_easy_slot",
    "tare_xbloom_scale",
    "import_xbloom_cloud_recipe",
    "search_xbloom_collective_recipes",
    "export_xbloom_recipe",
    "search_xbloom_my_recipes",
    "import_xbloom_my_recipe",
)

REMOVED_TOOLS = (
    "search_xbloom_cloud_recipes",
    "create_xbloom_cloud_recipe",
    "edit_xbloom_cloud_recipe",
    "delete_xbloom_cloud_recipe",
)


@pytest.mark.parametrize("tool_name", REGISTERED_TOOLS)
def test_prompt_mentions_every_registered_tool(tool_name):
    assert tool_name in XBLOOM_LLM_PROMPT


@pytest.mark.parametrize("tool_name", REMOVED_TOOLS)
def test_prompt_does_not_mention_removed_tools(tool_name):
    assert tool_name not in XBLOOM_LLM_PROMPT


def test_registered_tools_match_catalog():
    """REGISTERED_TOOLS must stay in lockstep with the actual catalog."""
    from custom_components.xbloom.llm.catalog import build_tools

    names = {tool.name for tool in build_tools(SimpleNamespace(), SimpleNamespace())}
    assert names == set(REGISTERED_TOOLS)
