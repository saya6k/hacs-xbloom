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
        """Start a manual pour with current slider values."""
        if not self._check_connected():
            return
        try:
            await self._ensure_pro_mode()
            # 8007 (RD_BREWER_IN) — "enter pour page" parity with the
            # official app's standalone manual pour screen. Not
            # functionally required (4506 alone is hardware-confirmed
            # sufficient, see AGENTS.md), sent for parity/robustness.
            await self.client._send_command(brewing._CMD_BREWER_IN)
            self._active_operation = "manual_pour"
            await self.client.brewer.start(
                volume=float(self.volume),
                temperature=float(self.temperature),
                flow_rate=self.flow_rate,
                water_source=self.water_source,
                pattern=self.pour_pattern,
            )
        except Exception as exc:
            _LOGGER.error("Pour error: %s", exc)

    async def async_grind(self) -> None:
        """Start grinding with current slider values."""
        if not self._check_connected():
            return
        try:
            await self._ensure_pro_mode()
            self._active_operation = "manual_grind"
            await self.client.grinder.start(size=self.grind_size, speed=self.rpm)
        except Exception as exc:
            _LOGGER.error("Grind error: %s", exc)

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
        """
        if not self._check_connected():
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
        actually armed or executing, the heavier stop/quit sequence below
        doesn't apply — 8017/quitRecipeStart is the one command the
        official app itself uses to dismiss that exact prompt (decompiled
        2026-07-17, see AGENTS.md).

        Also branches on ``_active_operation``: a manual grind or pour
        must be stopped via the ``GrinderController``/``BrewerController``'s
        own ``stop()`` (cmds 3505/4507), not the whole-recipe stop/quit
        sequence below, which targets an actual recipe execution.
        """
        if not self._check_connected():
            return
        active_operation = self._active_operation
        self._executing_recipe = False
        self._active_recipe_pours = None
        self.current_pour_index = None
        try:
            if self._pod_prompt_active:
                await brewing.async_dismiss_pod_prompt(self.client)
                self._pod_prompt_active = False
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
        # Restore the user's persisted mode if we had auto-switched to Pro
        # for an HA operation that is now cancelled.
        await self._restore_persisted_mode("cancel")

    async def async_tare_scale(self) -> None:
        """Zero the scale (cmd 8500)."""
        if not self._check_connected():
            return
        try:
            await brewing.async_tare(self.client)
        except Exception as exc:
            _LOGGER.error("Tare error: %s", exc)
