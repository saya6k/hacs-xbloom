"""Tests for OperationsMixin.async_pour opening the pour page before 4506.

The official app only sends BREWER_START (4506) from its pour page (jadx
2026-10-24, BrewerActivity). async_pour used to send a bare 4506 from
wherever the machine was; a one-shot pour was then reported running past
its volume (2026-10-24). It now runs the two-stage flow back to back:
8007, entry push (4510/8016), a gap, then 4506.
"""
from __future__ import annotations

import asyncio

import pytest

from custom_components.xbloom.coordinator import operations
from custom_components.xbloom.coordinator.operations import OperationsMixin


@pytest.fixture
def sleeps(monkeypatch):
    """Record the delays instead of sleeping through them."""
    recorded: list[float] = []

    async def _sleep(delay: float) -> None:
        recorded.append(delay)

    monkeypatch.setattr(operations.asyncio, "sleep", _sleep)
    return recorded


class _FakeBrewer:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls
        self.start_calls: list[dict] = []
        self.fail_enter = False

    async def enter_mode(self) -> bool:
        if self.fail_enter:
            raise RuntimeError("no ACK")
        self._calls.append("8007")
        return True

    async def set_temperature(self, temperature: float) -> bool:
        self._calls.append("4510")
        return True

    async def set_pattern(self, pattern: int) -> bool:
        self._calls.append("8016")
        return True

    async def start(self, **kwargs) -> bool:
        self._calls.append("4506")
        self.start_calls.append(kwargs)
        return True


class _Coordinator(OperationsMixin):
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.client = type("_Client", (), {})()
        self.client.brewer = _FakeBrewer(self.calls)
        self.volume = 100
        self.temperature = 93
        self.flow_rate = 3.0
        self.water_source = 0
        self.pour_pattern = 2
        self._armed_operation = None
        self._active_operation = None

    async def _async_ensure_connected(self) -> bool:
        return True

    async def _async_retry_while_sleeping(self, action) -> None:
        await action()


def test_async_pour_opens_the_pour_page_before_starting(sleeps):
    coordinator = _Coordinator()
    asyncio.run(coordinator.async_pour())

    assert coordinator.calls == ["8007", "4510", "8016", "4506"]
    # Settle after 8007, gap inside the entry push, gap before 4506.
    assert sleeps == [
        operations._POUR_ARM_SETTLE_S,
        operations._POUR_ARM_PUSH_GAP_S,
        operations._POUR_ARM_PUSH_GAP_S,
    ]
    assert coordinator._armed_operation is None
    assert coordinator._active_operation == "manual_pour"


def test_async_pour_passes_current_slider_values(sleeps):
    coordinator = _Coordinator()
    coordinator.volume = 250
    coordinator.temperature = 88
    asyncio.run(coordinator.async_pour())

    call = coordinator.client.brewer.start_calls[0]
    assert call["volume"] == 250.0
    assert call["temperature"] == 88.0


def test_async_pour_does_not_start_when_the_page_does_not_open(sleeps):
    coordinator = _Coordinator()
    coordinator.client.brewer.fail_enter = True
    asyncio.run(coordinator.async_pour())

    # No bare 4506 fallback: that is the off-page pour this replaces.
    assert coordinator.calls == []
    assert coordinator._active_operation is None
