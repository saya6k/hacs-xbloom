"""Studio colour from the serial number.

Kept free of HA imports so both the panel (product photo) and the
coordinator (the Repairs issue for an unknown code) can use it.
"""
from __future__ import annotations

# Studio colours sold (xbloom.com store, 2026-10) and the serial-number code
# for each (serialNumber[4:6]). 01-05 are the official app's own rule (app
# 2.2.5 jadx 2026-10-29, Device.getHomeImageRes: 02 white, 03 ic_machine_green,
# 04 ic_machine_gold, 05 ic_machine_twilight, else black). The app has no
# code for Offline Blue, so it stays a placeholder (None) until a machine of
# that colour reports its serial — the Repairs issue raised for an unknown
# code asks the owner to report it.
MACHINE_COLOR_CODES: dict[str, str | None] = {
    "midnight_black": "01",
    "moonlight_white": "02",
    "sage_green_green": "03",
    "sage_green_gold": "04",
    "twilight": "05",
    "offline_blue": None,
}
MACHINE_COLORS = tuple(MACHINE_COLOR_CODES)
_SERIAL_COLOR_CODES = {code: color for color, code in MACHINE_COLOR_CODES.items() if code}


def color_code(serial: str | None) -> str | None:
    """The two-character colour code in a serial, or None if too short."""
    if not serial or len(serial) < 6:
        return None
    return serial[4:6]


def color_from_serial(serial: str | None) -> str | None:
    """The machine colour the serial number encodes, if the code is known."""
    return _SERIAL_COLOR_CODES.get(color_code(serial) or "")
