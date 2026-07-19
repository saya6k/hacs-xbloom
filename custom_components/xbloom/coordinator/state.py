"""State derivation (DataUpdateCoordinator contract) and BLE event dispatch.

Part of the coordinator package split (Phase 3, structural only — see
constants.py's module docstring).
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict

from .constants import _BLE_SILENCE_TIMEOUT_S, DEFAULT_STATE

_LOGGER = logging.getLogger(__name__)


class StateMixin:
    """DataUpdateCoordinator's ``_async_update_data`` plus BLE event dispatch."""

    async def _async_update_data(self) -> Dict[str, Any]:
        """Pull fresh data from the BLE status object (no I/O needed).

        Also drives the connection supervisor, on the same tick cadence as
        the official Android app's AppDeviceManager poll loop (see
        AGENTS.md): reconnect if not connected (unless the user explicitly
        disconnected this session or we are in idle standby), drop the link
        if it has gone silent for too long (``_BLE_SILENCE_TIMEOUT_S``), and
        drop it after ``_session_timeout`` seconds of inactivity.
        """
        if self.client and self.client.is_connected:
            if (
                not self._force_reconnect_pending
                and not self.client.is_sleeping()
                and self.client.seconds_since_last_notification() > _BLE_SILENCE_TIMEOUT_S
            ):
                # Skipped while the machine reports itself asleep (cmds
                # 8009/8011/8023): a sleeping machine going quiet is normal,
                # not a wedged link, and treating it as one turned every
                # overnight idle period into a disconnect/reconnect loop.
                self._force_reconnect_pending = True
                self.hass.async_create_task(self._async_drop_stale_link())
                return {**DEFAULT_STATE}
            if (
                self._session_timeout > 0
                and not self._idle_standby_pending
                and not self._armed_operation
                and not self._active_operation
                and not self._pod_prompt_active
                and (time.monotonic() - self._last_activity_monotonic)
                > self._session_timeout
            ):
                self._idle_standby_pending = True
                self.hass.async_create_task(self._async_enter_idle_standby())
                return {**DEFAULT_STATE}
            try:
                s = self.client.status
                # Never trust the raw water_level_ok flag directly — it's
                # only ever set from the one-shot connect-time
                # RD_MachineInfo snapshot (payload[33]), which multiple
                # firmwares report as False at idle regardless of the
                # tank's real state (see the firmware-quirks section in
                # AGENTS.md). Hardware-reported 2026-07-17: this used to
                # trust the flag once MachineInfo had been observed
                # (proxied by serial_number), which showed a permanent
                # "problem" after a normal reconnect on a unit whose
                # connect-time snapshot happened to read False and never
                # fired a follow-up RD_ErrorLackOfWater (40522) to correct
                # it. Always derive from the event-driven flag instead —
                # it starts optimistic (no shortage) and only flips on an
                # actual water_shortage/water_refilled notification.
                water_ok = not self._water_shortage
                # Layer the richer states our own event/status tracking can
                # see on top of the vendored DeviceState value: no_beans /
                # water_shortage (the machine WAITS rather than refusing),
                # and starting/brewing/ready from the raw status-heartbeat
                # stream. The cmd-tagged path alone is unreliable here —
                # hardware-confirmed 2026-07-15: RD_GRINDER_BEGIN never
                # fired during ~11s of real grinding, RD_BREWER_BEGIN fires
                # immediately after commit (well before real pouring
                # starts), and RD_Grinder_Stop flips vendored state to IDLE
                # right as grinding *ends*, moments before pouring begins.
                # See ble/client.py's _scan_for_status_frame /
                # _RAW_STATE_LABEL_MAP and coordinator._no_beans /
                # _water_shortage for provenance.
                raw_label = s.raw_state_label
                if self._armed_operation:
                    # Highest priority of all — the two-stage arm/confirm
                    # manual button flow's armed state (2026-07-18) is
                    # pure HA-side bookkeeping, not inferred from
                    # telemetry at all, so it's even more certain than
                    # is_calibrating_grinder() below. armed_grind /
                    # armed_pour / armed_recipe — see _armed_operation's
                    # docstring in __init__.py.
                    state_str = f"armed_{self._armed_operation}"
                elif self.client.is_calibrating_grinder():
                    # Next-highest priority — a deliberate, HA-triggered
                    # action (see async_calibrate_grinder()) we know is
                    # actually running, not inferred from ambiguous
                    # telemetry.
                    state_str = "calibrating"
                elif self._no_beans:
                    state_str = "no_beans"
                elif self._water_shortage:
                    state_str = "water_shortage"
                elif raw_label:
                    state_str = raw_label
                else:
                    state_str = s.state.value
                    if state_str == "unknown":
                        # Vendored DeviceState defaults to UNKNOWN and only
                        # ever transitions to IDLE on a Grinder/Brewer
                        # Begin/Stop event (the upstream PyBloom's core/client.py) — on
                        # a connection where the machine has never
                        # ground/brewed yet, nothing ever sets it, so a
                        # genuinely idle, connected machine reports
                        # "unknown" forever (hardware-reported 2026-07-17).
                        # We're inside the `client.is_connected` branch
                        # here, so treat "connected + no error + no
                        # activity ever observed" as idle rather than a
                        # permanent placeholder.
                        state_str = "idle"
                data = {
                    "connected": True,
                    "weight": round(s.scale.weight, 1),
                    # None (not 0.0) when no real reading has ever arrived --
                    # RD_BREWER_TEMPERATURE (8108) rarely fires on some units
                    # (hardware-confirmed 2026-07-15: zero signal across 4
                    # separate brews on one unit), and 0.0C is never a real
                    # brewer reading, so treating it as "unknown" is safe and
                    # avoids showing a misleading temperature.
                    "temperature": round(s.brewer.temperature, 1) if s.brewer.temperature else None,
                    "state": state_str,
                    "grinder_running": s.grinder.is_running,
                    "brewer_running": s.brewer.is_running,
                    "water_level_ok": water_ok,
                    "version": s.version,
                    "serial_number": s.serial_number,
                    # Use the machine's reported mode when available;
                    # fall back to the persisted preference before
                    # MachineInfo arrives.
                    "mode": self.client._machine_mode() if s.serial_number else self._mode,
                    "error": None,
                    # Live readings from the machine's own knobs/heartbeat —
                    # see ble/client.py's RD_GRINDER_SIZE/SPEED/BREWER_MODE and
                    # RD_MachineInfo handling. live_grind_size: None until
                    # first observed — 0 (the dataclass default) is never a
                    # real grind size, so it means "not yet seen".
                    "live_grind_size": s.grinder.size or None,
                    # live_grind_speed: 0 IS a real, meaningful reading
                    # (the grinder isn't currently spinning) — unlike grind
                    # size, don't coerce it to None/Unknown. ble/client.py's
                    # RD_Grinder_Stop handling explicitly zeroes this on
                    # stop so it doesn't linger at a stale nonzero RPM.
                    "live_grind_speed": s.grinder.speed,
                    "voltage": getattr(s, "voltage", None),
                    # Advanced Features (Pour Radius / Vibration Amplitude) —
                    # only populated once a GET/SET response has actually
                    # arrived (client._scan_for_advanced_settings); these
                    # aren't part of the passive telemetry heartbeat.
                    "pour_radius": getattr(s, "pour_radius", None),
                    "vibration_amplitude": getattr(s, "vibration_amplitude", None),
                }
                if data["state"] != "idle":
                    # The machine doing anything at all — including a brew
                    # started from its own touchscreen — counts as activity,
                    # so idle standby never drops the link mid-operation.
                    self._note_activity()
                # Mirror the physical temperature/pattern knobs onto the
                # manual-pour setpoints so number.temperature and
                # select.*_pour_pattern track knob turns in real time — but
                # only while idle. The knobs (and the app) are locked out
                # during an active grind/brew/pause, so any RD_
                # BREWER_TEMPERATURE (8108) seen in that window is the
                # machine's own in-progress reading (e.g. heating toward a
                # recipe's target), not a knob turn — mirroring it would
                # clobber the user's manual-pour setpoint with brew-transient
                # noise. Once back to idle, the knob is live again and the
                # setpoint should track it as normal.
                if data["state"] == "idle":
                    if s.brewer.temperature:
                        self.temperature = round(s.brewer.temperature)
                    live_pattern = getattr(s, "pour_pattern_live", None)
                    if live_pattern is not None:
                        self.pour_pattern = live_pattern
                # If MachineInfo arrived since last poll, update the device registry
                # so HA shows the correct serial/firmware version in the device page.
                self._maybe_update_device_registry(data)
                return data
            except Exception as exc:
                _LOGGER.warning("Error reading XBloom status: %s", exc)
                return {**DEFAULT_STATE}
        self._maybe_schedule_reconnect()
        return {**DEFAULT_STATE}

    # ------------------------------------------------------------------
    # Event listener management (used by event.py entities)
    # ------------------------------------------------------------------

    def register_event_listener(self, callback: Callable[[str, str, dict], None]) -> None:
        """Register an entity callback to receive BLE events."""
        if callback not in self._event_listeners:
            self._event_listeners.append(callback)

    def unregister_event_listener(self, callback: Callable[[str, str, dict], None]) -> None:
        """Unregister an entity event callback (safe to call even if not registered)."""
        try:
            self._event_listeners.remove(callback)
        except ValueError:
            pass  # already removed or never registered — harmless

    def _finish_run(self) -> None:
        """Tear down the in-flight-run bookkeeping on any terminal signal.

        One shared teardown for completion AND machine-side failure — the
        flags gate the cancel branch, the pause target, and idle standby,
        so leaving them set past the run's real end misroutes all three.
        """
        self._executing_recipe = False
        self._active_recipe_pours = None
        self.current_pour_index = None
        self._active_operation = None

    def _dispatch_event(self, category: str, event_type: str, attributes: dict) -> None:
        """Forward a BLE event to all registered HA event entities.

        This method is called from XBloomClient._fire_event() which runs inside
        the bleak notification handler.  Bleak may invoke the handler from a
        background thread, so we must schedule the actual HA work on the HA
        event loop via call_soon_threadsafe to avoid race conditions.
        """
        _LOGGER.debug("XBloom event [%s] %s %s", category, event_type, attributes)

        # ── Machine-side unit/water-source change (cmd 8015) ──
        # "settings" is a coordinator-internal category: the event entities
        # filter on "error"/"notification", so this never surfaces there.
        if category == "settings" and event_type == "unit_change":
            if self.hass and self.hass.loop:
                attrs_copy = dict(attributes)
                self.hass.loop.call_soon_threadsafe(
                    lambda: self.hass.async_create_task(
                        self._async_sync_units_from_machine(attrs_copy)
                    )
                )
            return

        # Drive the water-shortage / no-beans flags from the BLE event stream.
        prev_shortage = self._water_shortage
        prev_no_beans = self._no_beans
        if category == "error" and event_type == "water_shortage":
            self._water_shortage = True
        elif category == "error" and event_type == "no_beans":
            self._no_beans = True
        elif category == "notification" and event_type == "water_refilled":
            # The firmware's own "tank refilled" notification (cmd 40522
            # with value=1 — see ble/client.py). Without this, the only clear
            # path was a successful brew, which async_execute_recipe's own
            # low-water gate blocks — a deadlock the user could only escape
            # by reconnecting (real-hardware report 2026-07-17).
            self._water_shortage = False
        elif category == "notification" and event_type in (
            "brewing_started", "pour_complete", "recipe_complete",
        ):
            # A successful brew implies water and beans were both available.
            self._water_shortage = False
            self._no_beans = False
        if (
            (prev_shortage != self._water_shortage or prev_no_beans != self._no_beans)
            and self.hass and self.hass.loop
        ):
            self.hass.loop.call_soon_threadsafe(
                lambda: self.hass.async_create_task(self.async_refresh())
            )

        # ── Track the machine's local "start this pod?" prompt ──
        if category == "notification" and event_type == "pod_detected":
            self._pod_prompt_active = True
        elif category == "notification" and event_type in (
            "grinding_started", "brewing_started",
        ):
            # A real brew actually started — the official app's own
            # arm+execute flow never sends 8017, so the prompt is
            # implicitly resolved by this point. Clear the flag so a
            # later cancel doesn't send 8017 mid-brew (never verified
            # safe in that state) instead of the real stop/quit sequence.
            self._pod_prompt_active = False

        # ── Track the active pour during recipe execution ──
        # RD_BLOOM ("bloom") fires per pour, coffee or manual, with a
        # 0-based pour_index (see ble/client.py). Only meaningful while a
        # recipe execute is in flight (async_execute_recipe snapshots
        # _active_recipe_pours) — a manual pour's single bloom event is
        # ignored here since there's no recipe pour list to look up.
        pour_index_changed = False
        if (
            category == "notification" and event_type == "bloom"
            and self._executing_recipe and self._active_recipe_pours
        ):
            idx = attributes.get("pour_index")
            if isinstance(idx, int) and 0 <= idx < len(self._active_recipe_pours):
                self.current_pour_index = idx
                self.flow_rate = float(self._active_recipe_pours[idx].flow_rate)
                pour_index_changed = True
        elif category == "notification" and event_type in (
            "pour_complete", "recipe_complete",
        ):
            self._finish_run()
        elif category == "error" and event_type in (
            "no_beans", "abnormal_dose_or_water", "abnormal_gear_position",
        ):
            # The official app treats a machine alarm as end-of-brew
            # (AppJ15AutoManager posts BleEnjoyEvent on ErrorBle1/
            # ErrorIdling and tears its run state down). Without this, an
            # errored-out brew left _active_operation set forever — wrong
            # cancel branch, wrong pause target, and idle standby
            # suppressed indefinitely. water_shortage is deliberately NOT
            # here: hardware-observed 2026-07-19 firing mid-brew while the
            # brew ran on to completion, and the app likewise excludes
            # ErrorLackOfWater from its terminal set.
            self._finish_run()
        elif (
            category == "notification" and event_type == "grinding_complete"
            and self._active_operation == "manual_grind"
        ):
            # Only a *manual* grind is fully done here — a coffee recipe's
            # own grind phase also fires this, but the recipe (brewing
            # next) isn't done yet, so _active_operation stays "recipe"
            # until pour_complete/recipe_complete above.
            self._active_operation = None
        if pour_index_changed and self.hass and self.hass.loop:
            self.hass.loop.call_soon_threadsafe(
                lambda: self.hass.async_create_task(self.async_refresh())
            )

        # ── Restore Easy Mode after HA-triggered operations finish ──
        # When we auto-switched to Pro for grind/pour/recipe, switch
        # back once the machine reports a completion event so the
        # physical slot buttons work again.
        if self._auto_switched_to_pro and category == "notification" and event_type in (
            "grinding_complete", "pour_complete", "recipe_complete",
        ):
            if self.hass and self.hass.loop:
                self.hass.loop.call_soon_threadsafe(
                    lambda: self.hass.async_create_task(
                        self._restore_persisted_mode(event_type)
                    )
                )

        def _do_dispatch() -> None:
            # Snapshot the list in case a listener un-registers during iteration
            for cb in list(self._event_listeners):
                try:
                    cb(category, event_type, attributes)
                except Exception as exc:
                    _LOGGER.error("Event listener error: %s", exc)

        if self.hass and self.hass.loop:
            self.hass.loop.call_soon_threadsafe(_do_dispatch)
        else:
            # Fallback: already on the right thread or hass not yet set
            _do_dispatch()
