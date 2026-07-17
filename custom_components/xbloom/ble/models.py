"""XBloom device status and recipe payload models.

Native replacement for ``src/xbloom/models/types.py`` and
``src/xbloom/models/recipes.py``. The status dataclasses fold in fields
that were previously bolted onto the vendored ``DeviceStatus`` instance as
untyped ad-hoc attributes at runtime (``is_calibrating_grinder``,
``is_sleeping``, ``mode_ack_hex``, ``mode_bytes``, ``raw_state_label``,
``pour_radius``, ``vibration_amplitude``) — see ``docs/en/protocol.md`` and
project memory for why each one exists.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, IntEnum
from typing import List, Optional


class DeviceState(Enum):
    """High-level operational state."""

    UNKNOWN = "unknown"
    IDLE = "idle"
    GRINDING = "grinding"
    BREWING = "brewing"
    PAUSED = "paused"
    ERROR = "error"
    SLEEPING = "sleeping"


class PourPattern(IntEnum):
    """Pour styles. CENTER=0, CIRCULAR=1, SPIRAL=2."""

    CENTER = 0
    CIRCULAR = 1
    SPIRAL = 2


class CupType(IntEnum):
    X_POD = 1
    OMNI_DRIPPER = 2
    OTHER = 3
    TEA = 4


class VibrationPattern(IntEnum):
    NONE = 0
    BEFORE = 1
    AFTER = 2
    BOTH = 3


@dataclass
class GrinderStatus:
    is_running: bool = False
    speed: int = 0
    size: int = 0
    position: int = 0


@dataclass
class BrewerStatus:
    is_running: bool = False
    temperature: float = 0.0
    target_temperature: float = 92.0
    mode: int = 0


@dataclass
class ScaleStatus:
    weight: float = 0.0
    is_tared: bool = False


@dataclass
class DeviceStatus:
    """Complete device status, including notification-derived state that
    has no dedicated ``RD_*`` cmd-tagged response (see docs/en/protocol.md's
    "raw status-heartbeat frame" entry and the advanced-settings/mode-switch
    quirks)."""

    state: DeviceState = DeviceState.UNKNOWN
    connected: bool = False
    grinder: GrinderStatus = field(default_factory=GrinderStatus)
    brewer: BrewerStatus = field(default_factory=BrewerStatus)
    scale: ScaleStatus = field(default_factory=ScaleStatus)

    serial_number: str = ""
    model: str = ""
    version: str = ""
    water_level_ok: bool = False
    water_volume: int = 0
    voltage: int = 0

    last_update: datetime = field(default_factory=datetime.now)

    # Raw MachineInfo mode-field bytes, cached at connect time.
    mode_bytes: Optional[bytes] = None
    # Freshest mode signal: the cmd-11511 mode-switch ACK payload as hex,
    # once at least one switch has been observed this session.
    mode_ack_hex: Optional[str] = None
    # Raw status-heartbeat label (starting/brewing/ready), overriding the
    # cmd-tagged `state` above only for the codes it covers.
    raw_state_label: Optional[str] = None
    is_calibrating_grinder: bool = False
    is_sleeping: bool = False
    pour_radius: Optional[int] = None
    vibration_amplitude: Optional[int] = None
    # Live pour-pattern knob turn (RD_BREWER_MODE), same raw ints as
    # coordinator.POUR_PATTERN_OPTIONS (0=center/1=circular/2=spiral).
    pour_pattern_live: Optional[int] = None


@dataclass
class PourStep:
    volume: int
    temperature: int
    flow_rate: float = 3.0
    pausing: int = 0
    pattern: PourPattern = PourPattern.SPIRAL
    vibration: VibrationPattern = VibrationPattern.NONE

    def __post_init__(self) -> None:
        if self.flow_rate < 3.0 or self.flow_rate > 3.5:
            if self.flow_rate != 0:
                raise ValueError(
                    f"Flow rate {self.flow_rate} out of range (3.0-3.5)"
                )
        if self.temperature != 0 and (self.temperature < 40 or self.temperature > 100):
            raise ValueError(
                f"Temperature {self.temperature} out of range (40-100)"
            )
        if self.volume < 0:
            raise ValueError("Volume must be non-negative")
        if self.pausing < 0:
            raise ValueError("Pause must be non-negative")


@dataclass
class XBloomRecipe:
    grind_size: int = 60
    total_water: int = 0
    rpm: int = 60
    cup_type: int = 0
    name: str = "Unknown"
    bean_weight: float = 15.0
    id: int = 0
    pours: List[PourStep] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not (0 <= self.grind_size <= 150):
            if self.grind_size != 0:
                raise ValueError(
                    f"Grind size {self.grind_size} out of range (1-150)"
                )
        valid_rpms = {0, 60, 70, 80, 90, 100, 110, 120}
        if self.rpm not in valid_rpms:
            raise ValueError(f"RPM {self.rpm} invalid (Must be multiple of 10 in 60-120)")
        if len(self.pours) > 20:
            raise ValueError("Max 20 pours allowed")
        if self.bean_weight < 0 or self.bean_weight > 100:
            raise ValueError(f"Bean weight {self.bean_weight} invalid (0-100)")


def build_recipe_payload(recipe: XBloomRecipe) -> bytes:
    """Compile an ``XBloomRecipe`` into the binary payload for commands
    8001/8004 (coffee) and 4513 (tea).

    Payload structure::

        LENGTH_BYTE (1 byte) | BODY | FOOTER (2 bytes: grindSize, totalWater*10)

    Per pour, in order:
      - sub-steps (4 bytes each: volume, temperature, pattern, vibration),
        with volume chunked into 127ml-max sub-steps
      - metadata (4 bytes: -pausing as u8 two's complement, 0, rpm (first
        pour only), flow_rate*10)

    Dose (bean weight) and cup type are NOT in this payload — they go via
    the separate bypass (8102) and set-cup (8104) commands.
    """
    parts: List[bytes] = []
    for i, pour in enumerate(recipe.pours):
        remaining_vol = pour.volume
        sub_steps: List[bytes] = []
        if remaining_vol > 127:
            chunks, remainder = divmod(remaining_vol, 127)
            sub_steps.extend(
                struct.pack("BBBB", 127, pour.temperature, int(pour.pattern), int(pour.vibration))
                for _ in range(chunks)
            )
            if remainder > 0:
                sub_steps.append(
                    struct.pack(
                        "BBBB", remainder, pour.temperature, int(pour.pattern), int(pour.vibration)
                    )
                )
        else:
            sub_steps.append(
                struct.pack(
                    "BBBB", remaining_vol, pour.temperature, int(pour.pattern), int(pour.vibration)
                )
            )
        parts.extend(sub_steps)

        pause_byte = (-pour.pausing) & 0xFF
        flow_byte = int(pour.flow_rate * 10) & 0xFF
        rpm_byte = (recipe.rpm & 0xFF) if i == 0 else 0
        parts.append(struct.pack("BBBB", pause_byte, 0, rpm_byte, flow_byte))

    body = b"".join(parts)
    footer = struct.pack("BB", recipe.grind_size & 0xFF, (recipe.total_water * 10) & 0xFF)
    return struct.pack("B", len(body)) + body + footer
