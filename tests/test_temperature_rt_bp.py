"""Manual-pour temperature RT/BP endpoints (T11 / E2).

The app's pour slider spans 39–96 °C: the min position means RT (room
temperature) and transmits 20.0 °C, the max means BP (boiling) and
transmits 98.0 °C, everything between is literal (jadx 2026-07-20,
`CoffeeConstantUtil.getTemperatureJs15RTBP` + the shared branch in
`checkAndSetTemperature`/`startWater`). The number entity mirrors that
range, and the knob mirror inverse-maps wire values so a machine sitting
in the RT/BP zone lands back on the matching slider endpoint.
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.xbloom.coordinator import operations
from custom_components.xbloom.coordinator.operations import OperationsMixin
from custom_components.xbloom.coordinator.state import StateMixin

ROOT = Path(__file__).parent.parent / "custom_components" / "xbloom"


@pytest.fixture(autouse=True)
def _no_delays(monkeypatch):
    monkeypatch.setattr(operations, "_POUR_ARM_SETTLE_S", 0)
    monkeypatch.setattr(operations, "_POUR_ARM_PUSH_GAP_S", 0)


class _Ops(OperationsMixin):
    def __init__(self, temperature: int) -> None:
        self.client = None
        self.temperature = temperature
        self.volume = 250
        self.flow_rate = 3.0
        self.water_source = 0
        self.pour_pattern = 0
        self._armed_operation = None
        self._active_operation = None


@pytest.mark.parametrize(
    ("slider", "wire"),
    [(39, 20.0), (40, 40.0), (55, 55.0), (95, 95.0), (96, 98.0)],
)
def test_wire_temperature_endpoint_mapping(slider, wire):
    assert _Ops(slider)._wire_temperature() == wire


class _FakeBrewer:
    def __init__(self) -> None:
        self.start_kwargs: list[dict] = []
        self.set_temperature_calls: list[float] = []
        self.set_pattern_calls: list[int] = []

    async def enter_mode(self) -> bool:
        return True

    async def start(self, **kwargs) -> bool:
        self.start_kwargs.append(kwargs)
        return True

    async def set_temperature(self, temperature: float) -> bool:
        self.set_temperature_calls.append(temperature)
        return True

    async def set_pattern(self, pattern: int) -> bool:
        self.set_pattern_calls.append(pattern)
        return True


class _OpsFull(_Ops):
    def __init__(self, temperature: int) -> None:
        super().__init__(temperature)
        self.client = SimpleNamespace(brewer=_FakeBrewer(), status=None)

    async def _async_ensure_connected(self) -> bool:
        return True

    async def _async_retry_while_sleeping(self, action):
        return await action()


def test_pour_start_sends_the_wire_value():
    coordinator = _OpsFull(96)
    asyncio.run(coordinator.async_pour())
    assert coordinator.client.brewer.start_kwargs[0]["temperature"] == 98.0


def test_entry_push_sends_the_wire_value():
    coordinator = _OpsFull(39)
    asyncio.run(coordinator.async_arm_pour())
    assert coordinator.client.brewer.set_temperature_calls == [20.0]


# ── inverse mapping in the knob mirror ───────────────────────────────────


class _StateCoordinator(StateMixin):
    def __init__(self) -> None:
        self.hass = SimpleNamespace(loop=None)
        self.client = SimpleNamespace(
            status=SimpleNamespace(
                screen="pour",
                brewer=SimpleNamespace(is_running=False),
            )
        )
        self.temperature = 55
        self.pour_pattern = 0
        self.volume = 250
        self._armed_operation = None


@pytest.mark.parametrize(
    ("wire", "slider"),
    [(20.0, 39), (98.0, 96), (55.0, 55), (40.0, 40), (95.0, 95)],
)
def test_knob_mirror_inverse_maps_wire_values(wire, slider):
    coordinator = _StateCoordinator()
    coordinator._apply_brewer_values({"temperature": wire})
    assert coordinator.temperature == slider


@pytest.mark.parametrize("slider", [39, 40, 55, 95, 96])
def test_round_trip_is_a_fixed_point(slider):
    ops = _Ops(slider)
    wire = ops._wire_temperature()
    coordinator = _StateCoordinator()
    coordinator._apply_brewer_values({"temperature": wire})
    assert coordinator.temperature == slider


def test_number_entity_spans_39_to_96():
    tree = ast.parse((ROOT / "number.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "XBloomTemperatureNumber":
            attrs = {
                s.targets[0].id: s.value.value
                for s in node.body
                if isinstance(s, ast.Assign)
                and isinstance(s.targets[0], ast.Name)
                and isinstance(s.value, ast.Constant)
            }
            assert attrs["_attr_native_min_value"] == 39
            assert attrs["_attr_native_max_value"] == 96
            return
    raise AssertionError("XBloomTemperatureNumber not found")
