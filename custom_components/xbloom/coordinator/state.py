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

    def _apply_grinder_knob(self, attrs: dict) -> None:
        """Mirror a grind-page knob push (8105 size / 8106 RPM / 9000 entry
        snapshot — the client's "grinder_knob" settings event) onto the
        grind-size/RPM number entities (T6, 2026-07-20).

        Gated on the machine actually being on its grind page with nothing
        running: a recipe execution's own 8105 push must not clobber the
        user's manual setpoints, and the app disables its sliders during a
        real grind too.
        """
        s = getattr(self.client, "status", None)
        if s is None or s.screen != "grind" or s.grinder.is_running:
            return
        size = attrs.get("size")
        rpm = attrs.get("rpm")
        changed = False
        if isinstance(size, int) and 1 <= size <= 80 and size != self.grind_size:
            self.grind_size = size
            changed = True
        if isinstance(rpm, int) and 60 <= rpm <= 120 and rpm != self.rpm:
            self.rpm = rpm
            changed = True
        if changed and self.hass and self.hass.loop:
            self.hass.loop.call_soon_threadsafe(self.async_update_listeners)

    def _apply_brewer_knob(self, attrs: dict) -> None:
        """Mirror a pour-page knob push (8108 temperature / 8107 pattern)
        onto the manual-pour setpoints (T7). Gated on the pour page being
        open with no pour running — an active brew's 8108 frames are the
        heater's own in-progress readings, not knob turns. Applies while
        HA-armed too: an armed page's knobs are still live.
        """
        s = getattr(self.client, "status", None)
        if s is None or s.screen != "pour" or s.brewer.is_running:
            return
        changed = self._apply_brewer_values(attrs)
        if changed and self.hass and self.hass.loop:
            self.hass.loop.call_soon_threadsafe(self.async_update_listeners)

    def _apply_brewer_page_entry(self, attrs: dict) -> None:
        """Seed the entities from a knob-entry settings snapshot (9001,
        T7) — volume included, unlike live knob turns (the page has no
        live volume push, only this snapshot). Suppressed while an HA arm
        is in flight: the snapshot carries the machine's own remembered
        values, which the entry push (async_arm_pour) is about to
        overwrite with HA's — mirroring them first would make that push
        a no-op echo.
        """
        if self._armed_operation == "pour":
            return
        s = getattr(self.client, "status", None)
        if s is None or s.screen != "pour" or s.brewer.is_running:
            return
        changed = self._apply_brewer_values(attrs)
        volume = attrs.get("volume")
        if isinstance(volume, int) and 30 <= volume <= 500 and volume != self.volume:
            self.volume = volume
            changed = True
        if changed and self.hass and self.hass.loop:
            self.hass.loop.call_soon_threadsafe(self.async_update_listeners)

    def _apply_brewer_values(self, attrs: dict) -> bool:
        """Shared temperature/pattern apply for the two brewer mirrors."""
        changed = False
        temperature = attrs.get("temperature")
        pattern = attrs.get("pattern")
        if (
            isinstance(temperature, (int, float))
            and 40 <= temperature <= 100
            and round(temperature) != self.temperature
        ):
            self.temperature = round(temperature)
            changed = True
        if isinstance(pattern, int) and pattern in (0, 1, 2) and pattern != self.pour_pattern:
            self.pour_pattern = pattern
            changed = True
        return changed

    def _tracked_live_grind_size(self, s) -> int | None:
        """sensor.live_grind_size's value: the size in use by an actual
        grind, frozen at its last in-grind value otherwise (T6). Knob
        turns while idle belong to the grind-size number entity (see
        ``_apply_grinder_knob``), not this sensor — before this, every
        knob click animated "live" grind size with nothing grinding.
        """
        if s.grinder.is_running:
            self._live_grind_size = s.grinder.size or None
        return self._live_grind_size

    # Last screen this reconcile observed — class default so every test
    # harness gets it without __init__ churn.
    _last_reconcile_screen = None

    def _reconcile_armed_with_screen(self, s) -> None:
        """Drop a stale grind/pour arm once the machine LEAVES the armed
        page for home — the user backed out with the knob (T5,
        2026-07-20). Without this, cancel later sends a quit command for a
        screen that is no longer open.

        Edge-triggered on the page→home transition, not home itself —
        hardware-found the same day: the machine keeps reporting home for
        ~1s after our 8006/8007 until the page code lands, so a
        level-triggered clear raced every arm whose next poll tick fell in
        that window (deterministically so on a fast tick). The armed page
        must have been *observed* before home clears it; an arm whose page
        report never arrives at all keeps relying on cancel, as before.

        Deliberately NOT applied to an armed recipe: its machine-side
        dismissal is unverified on hardware, and the arm send chain
        (8102→8104→8001) sits on the home screen far longer than the
        instant 8006/8007 page opens do. Recipe arms are cleared by
        cancel, the confirm press, or a machine-side start signal.
        """
        last = self._last_reconcile_screen
        self._last_reconcile_screen = s.screen
        if (
            s.screen == "home"
            and self._armed_operation in ("grind", "pour")
            # The armed op name and its page label are the same string.
            and last == self._armed_operation
        ):
            self._armed_operation = None

    def _derive_state_string(self, s) -> str:
        """The sensor.state derivation chain, in priority order.

        Extracted from ``_async_update_data`` (T4, 2026-07-20) so the
        priority table is unit-testable — see
        tests/test_standalone_state_derivation.py.
        """
        if self._armed_operation == "recipe":
            # Pure HA-side bookkeeping for the two-stage recipe button
            # (2026-07-18): a machine-visible start prompt, not a
            # standalone page — the machine reports it via 0x1E/0x1F
            # anyway, but our own arm is the more immediate signal.
            return "armed_recipe"
        if self.client.is_calibrating_grinder():
            # A deliberate, HA-triggered action (see
            # async_calibrate_grinder()) we know is actually running, not
            # inferred from ambiguous telemetry.
            return "calibrating_grinder"
        if self._no_beans:
            return "no_beans"
        if self._water_shortage:
            return "water_shortage"
        if s.raw_state_label:
            # starting/brewing/ready/awaiting_confirm/… — an activity in
            # progress always outranks whatever page the machine last
            # reported (the screen goes stale the moment activity codes
            # replace page codes on the heartbeat).
            return s.raw_state_label
        if (
            s.screen in ("grind", "pour", "scale")
            and not s.grinder.is_running
            and not s.brewer.is_running
        ):
            # Telemetry-driven standalone modes (T2 capture 2026-07-20):
            # the machine's own screen report covers knob-entered pages,
            # not just HA-armed ones. The is_running guards cover the
            # window where an operation began but no activity code has
            # landed yet.
            return f"standalone_{s.screen}"
        if s.screen is None and self._armed_operation in ("grind", "pour"):
            # Armed-bookkeeping fallback, only while the machine has not
            # reported any screen: one 2026-07-19 run showed no page code
            # after our own 8007. A reported home screen deliberately
            # wins over a stale armed flag ("telemetry wins").
            return f"standalone_{self._armed_operation}"
        state_str = s.state.value
        if state_str == "unknown":
            # Vendored DeviceState defaults to UNKNOWN and only ever
            # transitions on a Grinder/Brewer Begin/Stop event — on a
            # connection where the machine has never ground/brewed yet,
            # nothing ever sets it, so a genuinely idle, connected
            # machine reports "unknown" forever (hardware-reported
            # 2026-07-17). We're only called from the
            # `client.is_connected` branch, so treat "connected + no
            # error + no activity ever observed" as idle rather than a
            # permanent placeholder.
            return "idle"
        return state_str

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
                self._reconcile_armed_with_screen(s)
                state_str = self._derive_state_string(s)
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
                    # RD_MachineInfo handling. live_grind_size: scoped to an
                    # actual grind (frozen otherwise, None until the first
                    # one) — see _tracked_live_grind_size.
                    "live_grind_size": self._tracked_live_grind_size(s),
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
        if category == "settings" and event_type == "grinder_knob":
            # Grind-page knob push — mirror onto the number entities and
            # stop here (coordinator-internal, never surfaces on the
            # event entities).
            self._apply_grinder_knob(attributes)
            return
        if category == "settings" and event_type == "brewer_knob":
            self._apply_brewer_knob(attributes)
            return
        if category == "settings" and event_type == "brewer_page_entry":
            self._apply_brewer_page_entry(attributes)
            return

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
        # Synthesize "water_shortage_cleared" when the latched shortage
        # resolves, dispatched to the event entities after the real event
        # below. Deliberately the only "_cleared" event — water shortage is
        # the one error with a wire-level resolution signal (40522 value=1);
        # deriving "cleared" for the others would be a guess.
        _cleared_events: list[str] = []
        if prev_shortage and not self._water_shortage:
            _cleared_events.append("water_shortage_cleared")
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

        # ── Armed→active transition on machine-side starts (T5) ──
        # The user armed in HA but pressed the machine's knob to start:
        # transition the bookkeeping exactly as the HA confirm press would,
        # so pause/cancel target the right command family afterwards.
        # grinding_started with nothing armed/active is deliberately NOT
        # inferred as a manual grind — an NFC pod brew fires it too, and
        # the recipe cancel fallback (bare 40519) is the safe default.
        if category == "notification" and event_type == "easy_slot_started":
            # A brew from the machine's Easy Mode dial (8111) is a recipe
            # execution regardless of what, if anything, was armed.
            self._armed_operation = None
            self._armed_recipe_is_tea = False
            self._armed_recipe_tea_payload = None
            self._active_operation = "recipe"
        elif category == "notification" and event_type in (
            "grinding_started", "brewing_started",
        ):
            if self._armed_operation == "recipe":
                # Coffee-with-grind confirms via grinding_started; a
                # no-grind (bypass) recipe's first signal is
                # brewing_started.
                self._armed_operation = None
                self._armed_recipe_is_tea = False
                self._armed_recipe_tea_payload = None
                self._active_operation = "recipe"
            elif self._armed_operation == "grind" and event_type == "grinding_started":
                self._armed_operation = None
                self._active_operation = "manual_grind"
            elif self._armed_operation == "pour" and event_type == "brewing_started":
                self._armed_operation = None
                self._active_operation = "manual_pour"

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

        def _do_dispatch() -> None:
            # Snapshot the list in case a listener un-registers during iteration
            for cb in list(self._event_listeners):
                try:
                    cb(category, event_type, attributes)
                except Exception as exc:
                    _LOGGER.error("Event listener error: %s", exc)
            # Synthesized "_cleared" error events (see the flag block above)
            # ride the same dispatch, after the real event that caused them.
            for cleared in _cleared_events:
                for cb in list(self._event_listeners):
                    try:
                        cb("error", cleared, {})
                    except Exception as exc:
                        _LOGGER.error("Event listener error: %s", exc)

        if self.hass and self.hass.loop:
            self.hass.loop.call_soon_threadsafe(_do_dispatch)
        else:
            # Fallback: already on the right thread or hass not yet set
            _do_dispatch()
