"""Result flags must distinguish failed calls, confirmation, and device status."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from homeassistant.helpers import llm

from custom_components.xbloom.llm.catalog import build_tools
from custom_components.xbloom.llm.cloud_recipe import _cloud_failure
from custom_components.xbloom.llm.grind import XBloomGrindTool
from custom_components.xbloom.llm.local_recipe import XBloomDeleteRecipeTool
from custom_components.xbloom.llm.status import XBloomStatusTool


def call(tool, args=None):
    return asyncio.run(
        tool.async_call(None, llm.ToolInput(tool_name=tool.name, tool_args=args or {}), None)
    )


def test_device_error_is_status_data_not_tool_failure():
    coord = SimpleNamespace(
        client=SimpleNamespace(is_connected=True), mac_address="test", data={"error": "water_low"}
    )
    result = call(XBloomStatusTool(coord, None))
    assert isinstance(result, llm.ToolResult)
    assert not result.error
    assert result.data["error"] == "water_low"
    assert result.data["connected"]


def test_connection_failure_is_tool_error():
    coord = SimpleNamespace(
        client=None, async_connect=AsyncMock(return_value=False), mac_address="test"
    )
    result = call(XBloomStatusTool(coord, None))
    assert result.error
    assert result.data["error"] == "connect_failed"


def test_cloud_failure_preserves_details():
    result = _cloud_failure({"error": "login_failed", "message": "Denied"}, "import")
    assert result.error
    assert result.data["error"] == "login_failed"
    assert "Denied" in result.data["instruction"]


def test_delete_confirmation_is_not_a_failed_call_or_a_delete():
    coord = SimpleNamespace(delete_local_recipe=Mock())
    result = call(XBloomDeleteRecipeTool(coord, None), {"recipe": "coffee", "confirmed": False})
    assert not result.error
    assert result.data["confirmation_required"]
    coord.delete_local_recipe.assert_not_called()


def test_grind_arm_does_not_start_grinding():
    coord = SimpleNamespace(
        client=SimpleNamespace(is_connected=True),
        grind_size=50,
        rpm=80,
        async_arm_grind=AsyncMock(),
        async_grind=AsyncMock(),
        async_confirm_grind=AsyncMock(),
        async_update_listeners=Mock(),
    )
    result = call(XBloomGrindTool(coord, None))
    assert not result.error
    assert result.data["armed"]
    coord.async_arm_grind.assert_awaited_once()
    coord.async_grind.assert_not_awaited()
    coord.async_confirm_grind.assert_not_awaited()


def test_catalog_metadata_distinguishes_side_effects():
    tools = {tool.name: tool for tool in build_tools(None, None)}
    for tool in tools.values():
        assert tool.integration == "xbloom"
        assert tool.title
    for name in ("grind_xbloom", "pour_xbloom", "execute_xbloom_recipe"):
        assert not tools[name].annotations.read_only
        assert not tools[name].annotations.idempotent
        assert tools[name].annotations.open_world
    assert tools["delete_xbloom_recipe"].annotations.destructive
    assert not tools["delete_xbloom_recipe"].annotations.open_world
    assert tools["list_xbloom_recipes"].annotations.read_only
    assert not tools["list_xbloom_recipes"].annotations.open_world
    assert tools["search_xbloom_collective_recipes"].annotations.open_world
