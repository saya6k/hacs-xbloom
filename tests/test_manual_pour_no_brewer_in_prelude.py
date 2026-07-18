"""Tests for OperationsMixin.async_pour sending bare BREWER_START (4506)
only, with no RD_BREWER_IN (8007) prelude.

Hardware-reported 2026-07-18: a standalone manual pour left the machine
sitting on its own pour-page screen needing a manual touchscreen tap to
actually start, instead of pouring immediately. Root cause:
async_pour() sent 8007 ("enter pour page") then 4506 (BREWER_START)
back-to-back with no delay between them — unlike GrinderController.
start()'s own analogous enter_mode() -> 2.0s sleep -> GRINDER_START
sequence for the identical "enter mode, let the machine transition, then
start" shape, 4506 had nothing giving the machine time to finish
switching into the pour page before it arrived, and was apparently
getting dropped mid-transition. Fixed by removing the 8007 send
entirely, reverting to the bare-4506 behavior that was the one actually
confirmed working (see AGENTS.md / project memory
xbloom-manual-operation-command-targeting).
"""
from __future__ import annotations

import asyncio

from custom_components.xbloom.coordinator.operations import OperationsMixin


class _FakeBrewer:
    def __init__(self) -> None:
        self.start_calls: list[dict] = []

    async def start(self, **kwargs) -> bool:
        self.start_calls.append(kwargs)
        return True


class _FakeClient:
    def __init__(self) -> None:
        self.sent_commands: list[int] = []
        self.brewer = _FakeBrewer()

    async def _send_command(self, command, *args, **kwargs) -> bool:
        self.sent_commands.append(int(command))
        return True


class _Coordinator(OperationsMixin):
    def __init__(self) -> None:
        self.client = _FakeClient()
        self.volume = 100.0
        self.temperature = 93.0
        self.flow_rate = 3.0
        self.water_source = 0
        self.pour_pattern = 2
        self._active_operation = None

    def _check_connected(self) -> bool:
        return True

    async def _ensure_pro_mode(self) -> None:
        return None

    async def _async_retry_while_sleeping(self, action) -> None:
        await action()


def test_async_pour_sends_only_bare_brewer_start():
    coordinator = _Coordinator()
    asyncio.run(coordinator.async_pour())

    # No 8007 (or any other bare command) sent before the pour.
    assert coordinator.client.sent_commands == []
    assert len(coordinator.client.brewer.start_calls) == 1


def test_async_pour_passes_current_slider_values():
    coordinator = _Coordinator()
    coordinator.volume = 250.0
    coordinator.temperature = 88.0
    asyncio.run(coordinator.async_pour())

    call = coordinator.client.brewer.start_calls[0]
    assert call["volume"] == 250.0
    assert call["temperature"] == 88.0
