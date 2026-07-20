"""Pour radius / vibration amplitude / display brightness / grinder calibration.

Part of the coordinator package split (Phase 3, structural only — see
constants.py's module docstring).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from .constants import _pour_radius_level_to_raw, _vibration_level_to_raw

_LOGGER = logging.getLogger(__name__)


class AdvancedSettingsMixin:
    """Grinder calibration and the "Advanced Features" settings service."""

    async def async_calibrate_grinder(self) -> None:
        """Trigger the grinder gear-position calibration sweep (cmd 3502).

        Split back out from ``async_set_advanced_settings`` into its own
        ``button.calibrate_grinder`` on 2026-07-17 — a plain button fits
        a one-shot trigger action better than a settings-values service,
        and sidesteps ``config_entry_id`` service-call resolution
        entirely (unrelated hardware report the same day found that
        resolution was broken for *every* service — see
        ``__init__.py``'s ``_coordinators_for_call``, reinforcing that a
        button was the simpler, more robust choice here regardless).

        Sets ``is_calibrating_grinder`` and fires
        ``grinder_calibration_started`` here, at send time, rather than
        waiting for the machine's own 50038 (RD_CalibrateStart) push —
        hardware-confirmed 2026-07-17 that 50038 never arrived at all
        during a real calibration run on at least one unit, which would
        otherwise leave the whole calibration flow (state, events,
        completion detection) silently inert.

        Completion is ``RD_CurrentGrinder`` (40526) reporting exactly 85
        (see ble/client.py) — the *only* signal the official app's own
        ``CalibrateGrinderActivity.onEventBusEvent`` checks (decompiled
        2026-07-17). Also schedules ``_async_calibration_timeout_fallback``,
        mirroring the same activity's own 180s client-side timeout
        (``Observable.just(0).delay(180000, MILLISECONDS)``) so a lost or
        delayed 85 reading doesn't leave ``is_calibrating_grinder`` (and
        ``sensor.state == "calibrating_grinder"``) stuck forever. ``RD_Grinder_Stop``
        is deliberately *not* a completion signal — an earlier version of
        this fix treated it as one, but hardware-confirmed 2026-07-17 (a
        second, longer test) that it fires within ~5s of send as part of
        the calibration sequence's own startup/homing move, a full minute
        before the real 85 reading arrives; treating it as "done" closed
        the gate early and made the genuine completion event unreachable.
        """
        if not await self._async_ensure_connected():
            return
        try:
            # Only the raw send is retried while asleep (see
            # _async_retry_while_sleeping's docstring) — the bookkeeping
            # below must run exactly once regardless of how many attempts
            # the send took, or a retry would fire a duplicate
            # "grinder_calibration_started" event and schedule a second,
            # redundant 180s timeout fallback task.
            await self._async_retry_while_sleeping(self.client.async_calibrate_grinder)
            self.client.status.is_calibrating_grinder = True
            self.client._fire_event("notification", "grinder_calibration_started")
            await self.async_refresh()
            self.hass.async_create_task(self._async_calibration_timeout_fallback())
        except Exception as exc:
            _LOGGER.error("Calibrate grinder error: %s", exc)

    async def _async_calibration_timeout_fallback(self) -> None:
        """Mirror CalibrateGrinderActivity's own 180s client-side timeout:
        if the real completion signal (RD_CurrentGrinder == 85) hasn't
        arrived within 180s of send, declare it done anyway rather than
        leaving ``is_calibrating_grinder``/``sensor.state == "calibrating_grinder"``
        stuck indefinitely. A no-op if the real signal already cleared the
        flag (the common case) before this fires.
        """
        await asyncio.sleep(180)
        if self.client.is_calibrating_grinder():
            self.client.status.is_calibrating_grinder = False
            self.client._fire_event("notification", "grinder_calibration_complete")
            await self.async_refresh()

    async def _async_refresh_advanced_settings(self) -> None:
        """Fire-and-forget GET for pour_radius/vibration_amplitude, once
        per connect. These are request/response (not passive telemetry),
        so nothing populates the two sensors until this runs — see
        ble/client.py's CMD_GET_POUR_RADIUS module comment.

        Logged at INFO on our own logger (not the vendored xbloom.core.client
        one the SEND/RECV CMD lines use) — hardware debugging 2026-07-17
        found a real user setup where xbloom.core.client's output was
        entirely suppressed (a per-logger level override silencing that
        specific noisy namespace, common for the multi-Hz telemetry it
        logs) while custom_components.xbloom.* stayed visible, making the
        whole GET/response cycle unobservable without this.

        Callers must only invoke this once ``self.client.status.serial_number``
        is populated (RD_MachineInfo has actually arrived) — hardware-
        confirmed 2026-07-17 on the exact same user setup: firing this
        unconditionally right after ``client.connect()`` returns can lose
        the response entirely on a firmware that needs a *second* 8100
        handshake before MachineInfo shows up (the same "machine isn't
        really awake yet" quirk documented for the initial connect
        handshake — see AGENTS.md). This request/response command is just
        as vulnerable to that dead window as MachineInfo itself, so it's
        gated on the same signal (see ``async_connect``/
        ``_machine_info_retry_loop``, both of which now only call this
        once serial_number is confirmed non-empty).

        The two GETs need at least ~0.5s between them — hardware-confirmed
        2026-07-17 (four repeated trials on a real machine): a 0.3s gap
        made the vibration_amplitude GET consistently get no response at
        all (pour_radius always succeeded; the machine appears to still be
        busy replying to the first request when the second arrives, and
        silently drops it rather than queuing it), while 0.6s/1.0s/1.5s
        gaps all succeeded consistently. 0.8s below is used for margin.
        """
        _LOGGER.info("Requesting pour_radius / vibration_amplitude (cmd 11506/11508)…")
        try:
            await self.client.async_get_pour_radius()
            await asyncio.sleep(0.8)
            await self.client.async_get_vibration_amplitude()
            _LOGGER.info("Advanced settings GET sent (pour_radius/vibration_amplitude)")
        except Exception as exc:
            _LOGGER.warning("Advanced settings refresh failed: %s", exc)

    async def async_set_advanced_settings(
        self,
        *,
        pour_radius_level: Optional[int] = None,
        vibration_amplitude_level: Optional[int] = None,
        display_brightness_level: Optional[int] = None,
    ) -> dict:
        """Advanced Features — pour radius / vibration amplitude / display
        brightness, grouped into one service (matching the official app's
        own "Advanced Features" screen) rather than several always-visible
        entities for settings nobody adjusts often. At least one action
        must be requested.

        Grinder calibration used to be a fourth field here
        (``calibrate_grinder``) but was split back out to its own
        ``button.calibrate_grinder``/``async_calibrate_grinder()`` on
        2026-07-17 — hardware-reported: a real call with a real
        ``config_entry_id`` failed with "No XBloom machine matched the
        service call," which turned out to be an unrelated pre-existing
        bug in ``_coordinators_for_call`` (fixed the same day, see
        ``__init__.py``), but the report was reason enough to also
        reconsider bundling a one-shot trigger action into a
        settings-values service in the first place — a plain button is a
        better fit for "press to fire," and doesn't depend on
        ``config_entry_id`` resolution at all.

        Levels, not raw device values — mirrors the official app's own
        L1-L5 / L1-L6 / L1-L3 picker UIs (decompiled 2026-07-16, see
        AGENTS.md) rather than asking users to type an opaque number:

        - ``vibration_amplitude_level`` (0-5, L1-L6): a fixed absolute
          scale, ``raw = 1000 + level * 100`` — no ambiguity, matches
          MachineSetVibrationAmplitudeActivity exactly.
        - ``display_brightness_level`` (1-3, L1-L3): 3 fixed presets,
          ``raw`` one of 1/8/15 (see ``ble.constants.Command.SET_DISPLAY_BRIGHTNESS``)
          — matches MachineDisplayActivity exactly, also no ambiguity (no
          GET counterpart either — the official app tracks the current
          value from its own account/device record, not a fresh BLE read,
          so there's nothing for this integration to poll).
        - ``pour_radius_level`` (0-4, L1-L5): the official app centers
          these 5 levels on a **per-device factory value**
          (``Device.pouringRadiusInit``), fetched from xBloom's cloud
          account (see ``_cloud_client.get_pour_radius_init_center`` —
          reverse-engineered 2026-07-16, live-verified the same day
          against a real account/device, member_id 23237/serial
          J15A01B4CV030 returned a real 750). **Requires a logged-in
          cloud account** — rejected up front (``cloud_login_required``)
          otherwise, rather than silently substituting the current
          ``pour_radius`` reading as an approximate center; that
          approximation only holds on a machine nobody has ever changed
          the level on before, which isn't something this integration can
          verify, so it's no longer used. Still untested on real
          hardware — the BLE `SET` side (`11507`) is unverified even
          though the cloud lookup that feeds it now is.
        """
        if (
            pour_radius_level is None
            and vibration_amplitude_level is None
            and display_brightness_level is None
        ):
            return {
                "success": False,
                "error": "no_action",
                "message": "Specify at least one of pour_radius_level, vibration_amplitude_level, or display_brightness_level.",
            }
        if pour_radius_level is not None and not 0 <= pour_radius_level <= 4:
            return {
                "success": False,
                "error": "invalid_level",
                "message": "pour_radius_level must be 0-4 (L1-L5).",
            }
        if vibration_amplitude_level is not None and not 0 <= vibration_amplitude_level <= 5:
            return {
                "success": False,
                "error": "invalid_level",
                "message": "vibration_amplitude_level must be 0-5 (L1-L6).",
            }
        if display_brightness_level is not None and not 1 <= display_brightness_level <= 3:
            return {
                "success": False,
                "error": "invalid_level",
                "message": "display_brightness_level must be 1-3 (L1-L3).",
            }
        if pour_radius_level is not None and not self.cloud_client.logged_in:
            # Required, not opportunistic: without the cloud-fetched real
            # factory-default center, "level 2" is only an approximation
            # (the current value at call time) — see
            # _cloud_client.get_pour_radius_init_center's docstring. Reject
            # up front rather than silently shipping an unreliable value.
            return {
                "success": False,
                "error": "cloud_login_required",
                "message": "pour_radius_level requires an XBloom cloud account login (Options → Account) — this integration has no other way to know the machine's factory-default pour-radius center.",
            }
        if not await self._async_ensure_connected():
            return {
                "success": False,
                "error": "not_connected",
                "message": "The XBloom is not connected over Bluetooth.",
            }
        try:
            if pour_radius_level is not None:
                current = self.data.get("pour_radius")
                if current is None:
                    await self.client.async_get_pour_radius()
                    await asyncio.sleep(0.5)
                    current = self.data.get("pour_radius")
                if current is None:
                    return {
                        "success": False,
                        "error": "pour_radius_unknown",
                        "message": "Could not read the current pour radius from the machine — try again once connected.",
                    }
                serial = self.data.get("serial_number")
                if not serial:
                    return {
                        "success": False,
                        "error": "serial_unknown",
                        "message": "The machine's serial number isn't known yet — try again once MachineInfo has been read.",
                    }
                center = await self.cloud_client.get_pour_radius_init_center(serial, current)
                if center is None:
                    return {
                        "success": False,
                        "error": "cloud_center_unavailable",
                        "message": "Could not fetch the factory-default pour-radius center from XBloom's cloud account — try again later.",
                    }
                await self.client.async_set_pour_radius(
                    _pour_radius_level_to_raw(pour_radius_level, center)
                )
                # 0.8s, not 0.3s -- hardware-confirmed 2026-07-17 (same
                # finding as the pour_radius/vibration_amplitude GET pair
                # in _async_refresh_advanced_settings): a 0.3s gap between
                # two back-to-back type-2 commands consistently drops the
                # second one's ACK; 0.8s consistently succeeds.
                await asyncio.sleep(0.8)
            if vibration_amplitude_level is not None:
                await self.client.async_set_vibration_amplitude(
                    _vibration_level_to_raw(vibration_amplitude_level)
                )
                await asyncio.sleep(0.8)
            if display_brightness_level is not None:
                await self.client.async_set_display_brightness(display_brightness_level)
                await asyncio.sleep(0.3)
        except Exception as exc:
            _LOGGER.error("Advanced settings error: %s", exc, exc_info=True)
            return {
                "success": False,
                "error": "write_failed",
                "message": f"Advanced settings call failed: {exc}",
            }
        await self.async_refresh()
        return {"success": True}
