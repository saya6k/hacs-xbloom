"""Manual grind/pour, tare, pause/resume, and cancel.

Part of the coordinator package split (Phase 3, structural only — see
constants.py's module docstring).
"""
from __future__ import annotations

import asyncio
import logging

from .. import brewing
from ..ble.constants import Command
from .constants import _CMD_RECIPE_PAUSE, _CMD_RECIPE_RESTART

_LOGGER = logging.getLogger(__name__)

# Which command backs out of the machine screen each arm press opened.
# Decompiled from the official app 2026-07-19 (see project memory): its
# GrinderActivity/BrewerActivity onBackPressed() send APP_GRINDER_QUIT /
# APP_BREWER_QUIT, and RecipeDetailActivity/PodsDetailActivity's start
# dialog dismisses with APP_RECIPE_START_QUIT. RD_BackToHome (8022) — what
# this used to send for all three — is only ever sent by the app from its
# machine-settings screen, never to leave one of these.
#
# RECIPE_START_QUIT doubles as the dismissal for the machine's own local
# "start this pod?" prompt (RD_Pods/40501, fired as pod_detected the
# moment it reads the NFC tag, independent of anything HA armed) — the
# same dialog, reached from the machine's side instead of ours.
_ARMED_QUIT_COMMANDS = {
    "grind": Command.GRINDER_QUIT,
    "pour": Command.BREWER_QUIT,
    "recipe": Command.RECIPE_START_QUIT,
}

# Outcome-based stop verification (hardware 2026-07-20): a component stop
# (3505/4507) landing inside the machine's own start-transition window —
# between the begin report (9003/9005) and the run-begin (40506) — is
# silently dropped even though everything around it ACKs, the same
# mid-transition command-dropping shape as the old 8007→4506 race. A
# cancel pressed within ~2.5s of a knob start hit exactly that window and
# left the grinder running. Watch is_running for this long, then re-send
# once.
_STOP_VERIFY_ATTEMPTS = 10
_STOP_VERIFY_INTERVAL_S = 0.25

# Settle delay between 8007 ("enter pour page") and the entry push of HA's
# temperature/pattern (4510/8016) in async_arm_pour — the machine needs to
# finish its screen transition first (the 8007→4506 no-gap race is exactly
# what broke manual pour once; see async_pour's docstring). Value borrowed
# from GrinderController.start()'s analogous enter→2.0s→start sequence;
# tune on hardware if the pushes ever land before the page opens.
_POUR_ARM_SETTLE_S = 2.0
# Gap between the entry push's own two sends. Hardware 2026-07-20: 4510
# and 8016 fired 1ms apart — 4510 ACKed, 8016 was silently dropped (the
# machine kept its remembered pattern). The app never hits this because
# its sendMessage queue is ACK-gated (~370-380ms measured latency);
# 0.5s approximates that serialization.
_POUR_ARM_PUSH_GAP_S = 0.5


class OperationsMixin:
    """Manual pour/grind/tare and pause/resume/cancel, state-aware."""

    async def async_pour(self) -> None:
        """Start a manual pour with current slider values.

        The actual start send is wrapped in ``_async_retry_while_sleeping``
        (2026-07-18, hardware-reported): a pour started while the machine
        was asleep silently did nothing, since nothing resent it — see
        that method's docstring.

        Sends bare 4506 (BREWER_START) only — no 8007 (RD_BREWER_IN)
        prelude. Hardware-reported 2026-07-18: standalone manual pour left
        the machine sitting on its own pour-page screen needing a manual
        tap to actually start, instead of pouring immediately. Root cause:
        8007 ("enter pour page") and 4506 were being sent back-to-back with
        no delay between them — unlike GrinderController.start()'s own
        analogous enter_mode() → 2.0s sleep → GRINDER_START sequence for
        the identical "enter mode, let the machine transition, then start"
        shape, 4506 here had nothing giving the machine time to actually
        finish switching into the pour page before the start command
        arrived, and it was apparently getting dropped mid-transition. The
        8007 send was already documented as "not functionally required,
        4506 alone is hardware-confirmed sufficient" when added purely for
        app parity — removed rather than given an untested delay value,
        since the bare-4506 behavior it reverts to was the one actually
        confirmed working.
        """
        if not await self._async_ensure_connected():
            return
        try:
            self._active_operation = "manual_pour"
            await self._async_retry_while_sleeping(
                lambda: self.client.brewer.start(
                    volume=float(self.volume),
                    temperature=float(self.temperature),
                    flow_rate=self.flow_rate,
                    water_source=self.water_source,
                    pattern=self.pour_pattern,
                )
            )
        except Exception as exc:
            _LOGGER.error("Pour error: %s", exc)

    async def async_arm_pour(self) -> None:
        """First press of the two-stage manual-pour button flow
        (2026-07-18, HA button entity only — see ``_armed_operation``'s
        docstring in ``__init__.py``): sends ``RD_BREWER_IN`` (8007,
        "enter pour page") without starting the pour. Unlike the old
        removed 8007 prelude (see ``async_pour``'s docstring), this is
        safe: the real gap until the user presses confirm replaces the
        missing delay that caused the original regression.
        ``async_confirm_pour()`` sends the actual start command (with
        current slider values) on a second press of the same button.

        After the arm lands, HA's temperature/pattern setpoints are pushed
        to the page (4510/8016, T7 2026-07-20) so the machine shows what
        the entities say instead of its own remembered defaults —
        best-effort, like the app's own ``sendMessageNoShowFail`` senders,
        after a ``_POUR_ARM_SETTLE_S`` screen-transition delay.
        """
        if not await self._async_ensure_connected():
            return
        try:
            await self._async_retry_while_sleeping(
                lambda: self.client.brewer.enter_mode()
            )
            self._armed_operation = "pour"
        except Exception as exc:
            _LOGGER.error("Pour arm error: %s", exc)
            return
        await asyncio.sleep(_POUR_ARM_SETTLE_S)
        try:
            await self.client.brewer.set_temperature(float(self.temperature))
            await asyncio.sleep(_POUR_ARM_PUSH_GAP_S)
            await self.client.brewer.set_pattern(self.pour_pattern)
        except Exception as exc:
            _LOGGER.warning("Pour-page entry setpoint push failed (best-effort): %s", exc)

    async def async_confirm_pour(self) -> None:
        """Second press of the two-stage manual-pour button flow: send
        the pour-start command (4506) queued by ``async_arm_pour()``,
        with the current slider values.
        """
        if not await self._async_ensure_connected():
            return
        try:
            self._active_operation = "manual_pour"
            await self._async_retry_while_sleeping(
                lambda: self.client.brewer.start(
                    volume=float(self.volume),
                    temperature=float(self.temperature),
                    flow_rate=self.flow_rate,
                    water_source=self.water_source,
                    pattern=self.pour_pattern,
                )
            )
        except Exception as exc:
            _LOGGER.error("Pour confirm error: %s", exc)
        finally:
            self._armed_operation = None

    async def async_grind(self) -> None:
        """Start grinding with current slider values.

        See ``async_pour``'s docstring — same sleep-retry wrapping.
        """
        if not await self._async_ensure_connected():
            return
        try:
            self._active_operation = "manual_grind"
            await self._async_retry_while_sleeping(
                lambda: self.client.grinder.start(size=self.grind_size, speed=self.rpm)
            )
        except Exception as exc:
            _LOGGER.error("Grind error: %s", exc)

    async def async_arm_grind(self) -> None:
        """First press of the two-stage manual-grind button flow
        (2026-07-18, HA button entity only — see ``_armed_operation``'s
        docstring in ``__init__.py``): sends ``GRINDER_IN`` (size/speed,
        burr adjust) without starting. ``async_confirm_grind()`` sends
        the actual start command on a second press of the same button.
        """
        if not await self._async_ensure_connected():
            return
        try:
            await self._async_retry_while_sleeping(
                lambda: self.client.grinder.enter_mode(size=self.grind_size, speed=self.rpm)
            )
            self._armed_operation = "grind"
        except Exception as exc:
            _LOGGER.error("Grind arm error: %s", exc)

    async def async_confirm_grind(self) -> None:
        """Second press of the two-stage manual-grind button flow: send
        the bare grinder-start command queued by ``async_arm_grind()``.
        """
        if not await self._async_ensure_connected():
            return
        try:
            self._active_operation = "manual_grind"
            await self._async_retry_while_sleeping(
                lambda: self.client.grinder.confirm_start()
            )
        except Exception as exc:
            _LOGGER.error("Grind confirm error: %s", exc)
        finally:
            self._armed_operation = None

    async def async_pause_resume(self) -> None:
        """Toggle between pause and resume based on machine state.

        Branches on ``_active_operation`` (2026-07-17): a manual grind or
        pour (started via ``async_grind()``/``async_pour()``) must use the
        ``GrinderController``/``BrewerController``'s own pause/restart
        (cmds 8018/8020 grinder, 8019/8021 brewer — decompile-confirmed
        real, see AGENTS.md), not the whole-recipe pause/restart (40518/
        40524 — see ``_CMD_RECIPE_PAUSE``/``_CMD_RECIPE_RESTART``'s module
        comment), which only applies to an actual recipe execution.

        When the machine is brewing or grinding the button PAUSES.
        When paused the button RESUMES.
        When idle the button is a no-op.

        Also a no-op while ``_armed_operation`` is set (2026-07-18) —
        nothing is actually running yet during the two-stage arm/confirm
        button flow's armed state, so neither the grinder/brewer pause
        nor the whole-recipe pause command applies; use the confirm press
        or the cancel button instead.
        """
        if not await self._async_ensure_connected():
            return
        if self._armed_operation:
            return
        state = (self.data or {}).get("state", "unknown")
        try:
            if self._active_operation == "manual_grind":
                if state == "paused":
                    await self.client.grinder.restart()
                else:
                    await self.client.grinder.pause()
            elif self._active_operation == "manual_pour":
                if state == "paused":
                    await self.client.brewer.restart()
                else:
                    await self.client.brewer.pause()
            elif state == "paused":
                await self.client._send_command(_CMD_RECIPE_RESTART)
            elif state in ("starting", "brewing", "grinding"):
                await self.client._send_command(_CMD_RECIPE_PAUSE)
            else:
                # No-op unless something is verifiably pausable
                # (2026-07-19). 40518 is state-sensitive on this firmware:
                # from awaiting-confirm it STARTS a brew, and third-party
                # hardware testing reports it can abort a running one —
                # firing it blind from idle/unknown state is exactly the
                # kind of guess that ends badly. The button's availability
                # should track this same condition.
                _LOGGER.debug(
                    "Pause/resume pressed with nothing pausable (state=%s) — ignoring",
                    state,
                )
        except Exception as exc:
            _LOGGER.error("Pause/resume error (state=%s): %s", state, exc)

    async def async_cancel(self) -> None:
        """Emergency stop all operations.

        Branches on ``_pod_prompt_active`` (2026-07-17, folded in from a
        separate ``button.dismiss_pod`` — logically the same "cancel"
        action from the user's perspective, just targeting a different
        machine state): if the machine is only showing its own local
        "start this pod?" prompt (RD_Pods/pod_detected) with nothing
        actually queued or executing, the heavier stop/quit sequence below
        doesn't apply — 8017/quitRecipeStart is the one command the
        official app itself uses to dismiss that exact prompt (decompiled
        2026-07-17, see AGENTS.md).

        Also branches on ``_armed_operation`` (2026-07-18): this is the
        escape hatch for the two-stage arm/confirm manual button flow,
        which has no timeout — if the user armed an operation and never
        confirmed it, cancel backs out of whichever machine screen the arm
        press opened (``_ARMED_QUIT_COMMANDS``) rather than running the
        heavier stop sequence below, since nothing has actually started yet.

        Also branches on ``_active_operation``: a manual grind or pour
        must be stopped via the ``GrinderController``/``BrewerController``'s
        own ``stop()`` (cmds 3505/4507), not the whole-recipe stop/quit
        sequence below, which targets an actual recipe execution.

        Local bookkeeping is cleared BEFORE any BLE work and regardless of
        whether that work succeeds (2026-07-19, hardware-reported): cancel
        used to return early when disconnected, leaving ``_armed_operation``
        set, which made the *next* press of the same button confirm — i.e.
        actually start a grind or pour — instead of arming. The official
        app has the same ordering: both page ``onBackPressed()`` handlers
        and the recipe start dialog's cancel tear down their UI
        unconditionally (``finish()``/``dismiss()``) and fire the BLE
        command with empty success/fail callbacks.
        """
        active_operation = self._active_operation
        armed_operation = self._armed_operation
        pod_prompt_active = self._pod_prompt_active
        self._executing_recipe = False
        self._active_recipe_pours = None
        self.current_pour_index = None
        self._active_operation = None
        self._armed_operation = None
        self._armed_recipe_is_tea = False
        self._armed_recipe_tea_payload = None
        self._pod_prompt_active = False

        if not await self._async_ensure_connected():
            self.async_update_listeners()
            return

        # The armed quit and the pod-prompt dismissal are separate machine
        # screens that can both be up at once, and for an armed recipe they
        # are the same command — so collect, dedupe, then send.
        quit_commands: list[int] = []
        if armed_operation:
            quit_commands.append(_ARMED_QUIT_COMMANDS[armed_operation])
        if pod_prompt_active and Command.RECIPE_START_QUIT not in quit_commands:
            quit_commands.append(Command.RECIPE_START_QUIT)

        try:
            if quit_commands:
                for command in quit_commands:
                    await self.client._send_command(command)
            elif active_operation == "manual_grind":
                await self.client.grinder.stop()
                await self._async_verify_component_stop("grinder")
            elif active_operation == "manual_pour":
                await self.client.brewer.stop()
                await self._async_verify_component_stop("brewer")
            else:
                # Bare 40519, nothing else (2026-07-19) — matching the
                # official app's AppJ15AutoManager.stop(), which sends only
                # this. The old heavier sequence chased it with grinder/
                # brewer stops (3505/4507) and 8022, three commands the app
                # never sends when stopping a brew; 8022 in particular is
                # only ever sent from its machine-settings screen. Bare
                # 40519 is hardware-verified: the ratio-footer bisection
                # probes used it repeatedly and it cleanly stopped both
                # grind-stage and pour-stage runs.
                await self.client.stop_recipe()
        except Exception as exc:
            _LOGGER.error("Cancel error: %s", exc)

    async def _async_verify_component_stop(self, component: str) -> None:
        """Outcome-based retry for a manual grind/pour stop (see the
        ``_STOP_VERIFY_*`` constants' comment): if the component still
        reports running after the watch window, re-send its stop once —
        the first send hit the start-transition drop window. The re-send
        is harmless when the component stopped without our noticing (a
        stop at idle just echoes an ACK; live 2026-07-20)."""
        status = getattr(self.client, "status", None)
        comp = getattr(status, component, None) if status is not None else None
        if comp is None:
            return
        for _ in range(_STOP_VERIFY_ATTEMPTS):
            if not comp.is_running:
                return
            await asyncio.sleep(_STOP_VERIFY_INTERVAL_S)
        _LOGGER.warning(
            "%s still running %.1fs after stop — re-sending (start-transition drop window)",
            component, _STOP_VERIFY_ATTEMPTS * _STOP_VERIFY_INTERVAL_S,
        )
        if component == "grinder":
            await self.client.grinder.stop()
        else:
            await self.client.brewer.stop()

    async def async_tare_scale(self) -> None:
        """Zero the scale (cmd 8500). See ``async_pour``'s docstring —
        same sleep-retry wrapping."""
        if not await self._async_ensure_connected():
            return
        try:
            await self._async_retry_while_sleeping(lambda: brewing.async_tare(self.client))
        except Exception as exc:
            _LOGGER.error("Tare error: %s", exc)

    async def async_enter_scale_mode(self) -> None:
        """Show the scale screen on the machine (cmd 8003) — the official
        app sends this before opening its own scale page. See
        ``async_pour``'s docstring — same sleep-retry wrapping."""
        if not await self._async_ensure_connected():
            return
        try:
            await self._async_retry_while_sleeping(
                lambda: brewing.async_enter_scale(self.client)
            )
        except Exception as exc:
            _LOGGER.error("Scale mode enter error: %s", exc)

    async def async_exit_scale_mode(self) -> None:
        """Leave the scale screen (cmd 8014) — the official app's scale
        page sends this from its back handler."""
        if not await self._async_ensure_connected():
            return
        try:
            await self._async_retry_while_sleeping(
                lambda: brewing.async_exit_scale(self.client)
            )
        except Exception as exc:
            _LOGGER.error("Scale mode exit error: %s", exc)

    def _grind_page_open(self) -> bool:
        """Whether the machine reports its grind page open with nothing
        running — the telemetry-driven equivalent of an armed grind."""
        status = getattr(self.client, "status", None)
        return (
            status is not None
            and status.screen == "grind"
            and not status.grinder.is_running
        )

    async def async_sync_armed_grinder_settings(self) -> None:
        """Push the current grind size/RPM to a machine sitting on the
        grind screen after ``async_arm_grind()``.

        The official app has no dedicated adjust command: its
        ``GrinderActivity.adjustGrinder`` simply re-sends ``GRINDER_IN``
        (8006) with the new (size, speed) whenever a slider changes while
        on the grind page and not running, best-effort
        (``sendMessageNoShowFail``). No-op unless a grind is armed OR the
        machine reports its grind page open with nothing running (T6,
        2026-07-20 — a knob-opened page live-adjusts too, matching the
        telemetry-driven standalone states): while idle the values only
        feed the next start command's payload, and while actually grinding
        the app disables its sliders too.
        """
        if self._armed_operation != "grind" and not self._grind_page_open():
            return
        if not await self._async_ensure_connected():
            return
        try:
            await self.client.grinder.enter_mode(size=self.grind_size, speed=self.rpm)
        except Exception as exc:
            _LOGGER.warning("Armed grinder adjust failed: %s", exc)

    def _pour_page_open(self) -> bool:
        """Whether the machine reports its pour page open with nothing
        running — the telemetry-driven equivalent of an armed pour."""
        status = getattr(self.client, "status", None)
        return (
            status is not None
            and status.screen == "pour"
            and not status.brewer.is_running
        )

    async def async_sync_armed_brewer_temperature(self) -> None:
        """Push the current temperature to a machine sitting on the pour
        screen after ``async_arm_pour()`` — or knob-opened (T7, matching
        ``async_sync_armed_grinder_settings``'s gate) — (cmd 4510,
        temp × 10), mirroring the official app's
        ``checkAndSetTemperature``."""
        if self._armed_operation != "pour" and not self._pour_page_open():
            return
        if not await self._async_ensure_connected():
            return
        try:
            await self.client.brewer.set_temperature(float(self.temperature))
        except Exception as exc:
            _LOGGER.warning("Armed brewer temperature adjust failed: %s", exc)

    async def async_sync_armed_brewer_pattern(self) -> None:
        """Push the current pour pattern to a machine sitting on the pour
        screen after ``async_arm_pour()`` — or knob-opened (T7) — (cmd
        8016), mirroring the official app's ``checkAndSetSpiral``."""
        if self._armed_operation != "pour" and not self._pour_page_open():
            return
        if not await self._async_ensure_connected():
            return
        try:
            await self.client.brewer.set_pattern(self.pour_pattern)
        except Exception as exc:
            _LOGGER.warning("Armed brewer pattern adjust failed: %s", exc)
