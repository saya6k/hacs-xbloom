"""Manual grind/pour, tare, pause/resume, and cancel.

Part of the coordinator package split (Phase 3, structural only — see
constants.py's module docstring).
"""
from __future__ import annotations

import asyncio
import logging

from .. import brewing
from .constants import _CMD_RECIPE_PAUSE, _CMD_RECIPE_RESTART

_LOGGER = logging.getLogger(__name__)


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
        if not self._check_connected():
            return
        try:
            await self._ensure_pro_mode()

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
        """
        if not self._check_connected():
            return
        try:
            await self._ensure_pro_mode()
            await self._async_retry_while_sleeping(
                lambda: self.client.brewer.enter_mode()
            )
            self._armed_operation = "pour"
        except Exception as exc:
            _LOGGER.error("Pour arm error: %s", exc)

    async def async_confirm_pour(self) -> None:
        """Second press of the two-stage manual-pour button flow: send
        the pour-start command (4506) queued by ``async_arm_pour()``,
        with the current slider values.
        """
        if not self._check_connected():
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
        if not self._check_connected():
            return
        try:
            await self._ensure_pro_mode()
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
        if not self._check_connected():
            return
        try:
            await self._ensure_pro_mode()
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
        if not self._check_connected():
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
        if not self._check_connected():
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
            else:
                if state == "paused":
                    await self.client._send_command(_CMD_RECIPE_RESTART)
                else:
                    await self.client._send_command(_CMD_RECIPE_PAUSE)
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
        confirmed it, cancel just backs out of whatever "enter mode"/
        queued-recipe screen is showing (8022, Back to Home) rather than
        running the heavier stop sequence below, since nothing has
        actually started yet.

        Also branches on ``_active_operation``: a manual grind or pour
        must be stopped via the ``GrinderController``/``BrewerController``'s
        own ``stop()`` (cmds 3505/4507), not the whole-recipe stop/quit
        sequence below, which targets an actual recipe execution.
        """
        if not self._check_connected():
            return
        active_operation = self._active_operation
        armed_operation = self._armed_operation
        self._executing_recipe = False
        self._active_recipe_pours = None
        self.current_pour_index = None
        try:
            if self._pod_prompt_active:
                await brewing.async_dismiss_pod_prompt(self.client)
                self._pod_prompt_active = False
            elif armed_operation:
                await self.client._send_command(brewing._CMD_BACK_TO_HOME)
            elif active_operation == "manual_grind":
                await self.client.grinder.stop()
            elif active_operation == "manual_pour":
                await self.client.brewer.stop()
            else:
                await self.client.stop_recipe()
                await asyncio.sleep(0.3)
                await self.client.grinder.stop()
                await self.client.brewer.stop()
                await asyncio.sleep(0.3)
                # Reset the machine's UI/mode state to the home screen.
                # Without this the machine stays in whatever screen was
                # active (e.g. tea recipe UI) after the hardware stops.
                await self.client._send_command(brewing._CMD_BACK_TO_HOME)
        except Exception as exc:
            _LOGGER.error("Cancel error: %s", exc)
        self._active_operation = None
        self._armed_operation = None
        self._armed_recipe_is_tea = False
        self._armed_recipe_tea_payload = None
        # Restore the user's persisted mode if we had auto-switched to Pro
        # for an HA operation that is now cancelled.
        await self._restore_persisted_mode("cancel")

    async def async_tare_scale(self) -> None:
        """Zero the scale (cmd 8500). See ``async_pour``'s docstring —
        same sleep-retry wrapping."""
        if not self._check_connected():
            return
        try:
            await self._async_retry_while_sleeping(lambda: brewing.async_tare(self.client))
        except Exception as exc:
            _LOGGER.error("Tare error: %s", exc)
