"""Update entity for XBloom — informational firmware-version tracking only.

No install/flash capability: sending the machine's own OTA sequence (cmd
8100 handshake -> 8101 -> YMODEM transfer) from this integration would risk
bricking a real device with no rollback we control, and isn't reversible
the way every other action here is. This entity only tells the user their
current firmware and the actual latest one xBloom has published, plus its
real release notes — see ``_cloud_client.get_latest_firmware()`` for the
live endpoint this polls and coordinator.py's firmware-version block for
the version gates this same ``_firmware_build`` helper feeds for Easy Mode
/ tea recipes.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.components.update import UpdateEntity, UpdateDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import XBloomCoordinator, _firmware_build

_LOGGER = logging.getLogger(__name__)

# xBloom ships firmware roughly every 2-4 months (see coordinator.py's
# version-history comment) and this hits their production API, not a
# dedicated status/CDN endpoint — there's no published rate limit, so
# staying well under anything reasonable matters more than freshness.
# Once a day is already far more responsive than needed.
SCAN_INTERVAL = timedelta(hours=24)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: XBloomCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    async_add_entities([XBloomFirmwareUpdateEntity(coordinator, entry)])


class XBloomFirmwareUpdateEntity(CoordinatorEntity[XBloomCoordinator], UpdateEntity):
    """Reports current vs. actual-latest firmware, fetched live from
    xBloom's own update-check API. No ``install()`` — ``_attr_supported_features``
    is deliberately left at its default (0), so HA shows no update button,
    only the version comparison + release notes.

    ``installed_version`` tracks the BLE coordinator (push updates, no
    polling needed for that half). The "what's the latest" half is a
    separate, slow poll (``SCAN_INTERVAL`` above) against xBloom's cloud
    API — enabled by setting ``_attr_should_poll = True`` alongside the
    coordinator subscription, so both update paths run independently.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "firmware"
    _attr_unique_id = "xbloom_firmware_update"
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_should_poll = True

    def __init__(self, coordinator: XBloomCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._latest: dict | None = None

    @property
    def device_info(self):
        return self.coordinator.device_info

    @property
    def installed_version(self) -> str | None:
        return self.coordinator.data.get("version") or None

    @property
    def latest_version(self) -> str | None:
        if self._latest is None:
            # Never successfully polled yet — report "up to date" rather
            # than guessing at a version we don't actually know.
            return self.installed_version
        return self._latest["version"]

    @property
    def release_summary(self) -> str | None:
        if not self._latest:
            return None
        notes = self._latest["release_notes"]
        return notes.splitlines()[0] if notes else None

    @property
    def release_url(self) -> str | None:
        return self._latest["download_url"] if self._latest else None

    async def async_release_notes(self) -> str | None:
        return self._latest["release_notes"] if self._latest else None

    async def async_update(self) -> None:
        """Slow poll (SCAN_INTERVAL) against xBloom's live firmware-check
        API. Never raises — a failed/blocked check just keeps whatever was
        last known (or None, before the first success)."""
        latest = await self.coordinator.cloud_client.get_latest_firmware()
        if latest is None:
            _LOGGER.debug("Firmware update check failed or returned nothing; keeping last known")
            return
        current_build = _firmware_build(self.installed_version)
        latest_build = _firmware_build(latest["version"])
        if current_build is not None and latest_build is not None and latest_build < current_build:
            # A live "latest" older than what's installed means our parse
            # of one side is wrong, not that firmware time-traveled
            # backwards — don't show a nonsensical downgrade prompt.
            _LOGGER.warning(
                "Firmware check returned %s, older than installed %s — ignoring",
                latest["version"], self.installed_version,
            )
            return
        self._latest = latest
