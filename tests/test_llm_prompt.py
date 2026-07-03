"""XBLOOM_LLM_PROMPT must describe the current tool surface (SPEC §5).

Mirrors the registration list in llm_api.XBloomCoffeeAPI — update both
together when a tool is added/removed/renamed.
"""
from __future__ import annotations

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
