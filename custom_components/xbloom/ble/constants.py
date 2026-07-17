"""XBloom Studio BLE command table.

Native replacement for ``src/xbloom/protocol/constants.py``'s
``XBloomCommand``/``XBloomResponse`` plus the outbound command constants
previously scattered across ``brewing.py``/``coordinator.py``/``_client.py``.
Mirrors ``docs/en/protocol.md``'s command table exactly — keep both in sync;
that document is the narrative reference (payload shapes, status, quirks),
this module is the source of truth for the actual integers.

``Command`` covers every id this integration sends; ``Response`` covers
every id this integration receives and dispatches on. Some real protocol
ids are used only one way in this integration and therefore appear in only
one enum (e.g. 4508 is send-only here: there is no inbound "water source
set" acknowledgement this integration listens for).
"""
from __future__ import annotations

from enum import IntEnum

# BLE GATT UUIDs.
SERVICE_UUID = "0000e0ff-3c17-d293-8e48-14fe2e4da212"
WRITE_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID = "0000ffe2-0000-1000-8000-00805f9b34fb"
READ_CHAR_UUID = "0000ffe3-0000-1000-8000-00805f9b34fb"


class Command(IntEnum):
    """Outbound command ids (``APP_*`` in the reference upstream's naming)."""

    HANDSHAKE = 8100
    GRINDER_START = 3500
    CALIBRATE_GRINDER = 3502
    GRINDER_STOP = 3505
    BREWER_START = 4506
    BREWER_STOP = 4507
    BREWER_SET_TEMPERATURE = 4510
    WATER_SOURCE_SET = 4508
    TEA_RECIPE_MAKE = 4512
    TEA_RECIPE_CODE = 4513
    RECIPE_SEND_AUTO = 8001
    RECIPE_EXECUTE = 8002
    RECIPE_SEND_MANUAL = 8004
    GRINDER_IN = 8006
    BREWER_IN = 8007
    GRINDER_QUIT = 8012
    BREWER_QUIT = 8013
    BREWER_SET_PATTERN = 8016
    RECIPE_START_QUIT = 8017
    GRINDER_PAUSE = 8018
    BREWER_PAUSE = 8019
    GRINDER_RESTART = 8020
    BREWER_RESTART = 8021
    BACK_TO_HOME = 8022
    SET_BYPASS = 8102
    SET_DISPLAY_BRIGHTNESS = 8103
    SET_CUP = 8104
    POUR_RADIUS_GET = 11506
    POUR_RADIUS_SET = 11507
    VIBRATION_AMPLITUDE_GET = 11508
    VIBRATION_AMPLITUDE_SET = 11509
    EASY_SLOT_SEND = 11510
    EASY_MODE_SWITCH = 11511
    EASY_SLOT_ORDER = 11512
    RECIPE_PAUSE = 40518
    RECIPE_STOP = 40519
    RECIPE_RESTART = 40524
    SCALE_TARE = 8500


# Type-2 packets (packet offset 2 == 0x02) — everything else in Command is
# type-1. Their responses carry marker byte 0xC2, not the usual 0xC1 (see
# framing.py), and need >=0.8s spacing between back-to-back sends.
TYPE2_COMMANDS = frozenset(
    {
        Command.POUR_RADIUS_GET,
        Command.POUR_RADIUS_SET,
        Command.VIBRATION_AMPLITUDE_GET,
        Command.VIBRATION_AMPLITUDE_SET,
        Command.EASY_SLOT_SEND,
        Command.EASY_MODE_SWITCH,
        Command.EASY_SLOT_ORDER,
    }
)

# Minimum spacing between two back-to-back type-2 sends — a shorter gap
# reliably drops the second command's response (hardware-confirmed at 0.3s
# fail / 0.8s+ succeed). See docs/en/protocol.md.
TYPE2_COMMAND_GAP_S = 0.8


class Response(IntEnum):
    """Inbound (``RD_*``) command ids this integration dispatches on."""

    MACHINE_SLEEPING = 8009
    MACHINE_NOT_SLEEPING = 8011
    UNIT_CHANGE = 8015
    MACHINE_ACTIVITY = 8023
    GRINDER_SIZE = 8105
    GRINDER_SPEED = 8106
    BREWER_MODE = 8107
    BREWER_TEMPERATURE = 8108
    EASYMODE_BEGIN = 8111
    ABNORMAL_GEAR_POSITION = 8203
    ABNORMAL_DOSE_OR_WATER = 8204
    IN_GRINDER = 9000
    IN_BREWER = 9001
    IN_SCALE = 9002
    GRINDER_BEGIN = 9003
    OUT_GRINDER = 9004
    BREWER_BEGIN = 9005
    OUT_BREWER = 9006
    OUT_SCALE = 9008
    GRINDER_PAUSE = 9009
    BREWER_PAUSE = 9010
    TEA_RECIPE_RESTART = 9011
    TEA_RECIPE_SOAK = 9012
    CURRENT_WEIGHT = 10507
    EASYMODE_TYPE = 11511  # mode-switch ACK; also a Command (the switch itself)
    EASYMODE_RECIPE_STATE = 11518
    CURRENT_WEIGHT2 = 20501
    PODS = 40501
    BREWER_COFFEE_START = 40502
    GEAR_REPORT = 40505
    GRINDER_STOP = 40507
    BLOOM = 40510
    BREWER_STOP = 40511
    ENJOY = 40512
    ENJOY2 = 40513
    TEA_RECIPE_PAUSE = 40515
    ERROR_IDLING = 40517
    BYPASS = 40520
    MACHINE_INFO = 40521
    ERROR_LACK_OF_WATER = 40522
    WATER_VOLUME = 40523
    EASYMODE_RECIPE_NUM = 40525
    CURRENT_GRINDER = 40526
    BEFORE_VIBRATION = 40527
    CALIBRATE_START = 50038
    CALIBRATING = 50039


def command_name(cmd: int) -> str:
    """Best-effort name for a raw command id, for logging."""
    try:
        return Command(cmd).name
    except ValueError:
        try:
            return Response(cmd).name
        except ValueError:
            return f"UNKNOWN_{cmd}"
