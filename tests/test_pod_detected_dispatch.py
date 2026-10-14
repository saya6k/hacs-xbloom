"""The coordinator holds pod_detected until the cloud pod lookup returns,
then fires it once with the merged attributes — and falls back to the
bare xid on a failure or a lookup slower than _POD_LOOKUP_TIMEOUT_S.
"""
from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("homeassistant")

from custom_components.xbloom.coordinator import state as state_module
from tests.test_finish_run_and_pause_gate import _Coordinator


class _LoopHass:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.tasks: list[asyncio.Task] = []

    def async_create_task(self, coro):
        task = self.loop.create_task(coro)
        self.tasks.append(task)
        return task


class _FakeCloud:
    def __init__(self, result=None, exc=None, delay=0.0) -> None:
        self.result, self.exc, self.delay = result, exc, delay

    async def fetch_pod_detail(self, xid):
        await asyncio.sleep(self.delay)
        if self.exc:
            raise self.exc
        return self.result


async def _dispatch_pod(cloud: _FakeCloud) -> tuple[_Coordinator, list]:
    coordinator = _Coordinator()
    coordinator.hass = _LoopHass(asyncio.get_running_loop())
    coordinator.cloud_client = cloud
    log: list = []
    coordinator._event_listeners.append(lambda *event: log.append(event))
    coordinator._dispatch_event("notification", "pod_detected", {"xid": "KR0005"})
    await asyncio.sleep(0)  # let call_soon_threadsafe schedule the task
    await asyncio.gather(*coordinator.hass.tasks)
    return coordinator, log


def test_pod_detected_fires_once_with_cloud_detail():
    _, log = asyncio.run(
        _dispatch_pod(_FakeCloud(result={"name": "Mucho Berry", "recipes": []}))
    )
    assert log == [(
        "notification", "pod_detected",
        {"xid": "KR0005", "name": "Mucho Berry", "recipes": []},
    )]


@pytest.mark.parametrize(
    "cloud",
    [_FakeCloud(result=None), _FakeCloud(exc=RuntimeError("boom"))],
    ids=["unknown-xid", "lookup-raises"],
)
def test_pod_detected_falls_back_to_bare_xid(cloud):
    _, log = asyncio.run(_dispatch_pod(cloud))
    assert log == [("notification", "pod_detected", {"xid": "KR0005"})]


def test_slow_lookup_times_out_to_bare_xid(monkeypatch):
    monkeypatch.setattr(state_module, "_POD_LOOKUP_TIMEOUT_S", 0.01)
    _, log = asyncio.run(_dispatch_pod(_FakeCloud(result={"name": "late"}, delay=1)))
    assert log == [("notification", "pod_detected", {"xid": "KR0005"})]


def test_pod_prompt_flag_is_set_before_the_lookup_returns():
    # The cancel button's 8017 branch must not wait on the network.
    async def run():
        coordinator = _Coordinator()
        coordinator.hass = _LoopHass(asyncio.get_running_loop())
        coordinator.cloud_client = _FakeCloud(result={}, delay=1)
        coordinator._dispatch_event("notification", "pod_detected", {"xid": "KR0005"})
        flag = coordinator._pod_prompt_active
        await asyncio.sleep(0)
        for task in coordinator.hass.tasks:
            task.cancel()
        return flag

    assert asyncio.run(run()) is True
