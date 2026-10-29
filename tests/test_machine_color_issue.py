"""Repairs issue for a serial-number colour code the integration can't map.

01-05 are known (the official app 2.2.5's own rule). Any
other code falls back to the black photo and raises a Repairs issue asking
the owner to report the colour; only the two-character code goes into the
pre-filled GitHub link, never the full serial.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import unquote

from custom_components.xbloom.coordinator import connection
from custom_components.xbloom.coordinator.connection import ConnectionMixin


def _sync(serial: str):
    coordinator = SimpleNamespace(hass=object(), entry_id="e1")
    with patch.object(connection.ir, "async_create_issue") as create, patch.object(
        connection.ir, "async_delete_issue"
    ) as delete:
        ConnectionMixin._sync_machine_color_issue(coordinator, serial)
    return create, delete


def test_unknown_code_raises_a_repairs_issue():
    create, delete = _sync("J15A06B4CV030")
    delete.assert_not_called()
    args, kwargs = create.call_args
    assert args[1:] == ("xbloom", "unknown_machine_color_e1")
    assert kwargs["translation_key"] == "unknown_machine_color"
    assert kwargs["translation_placeholders"]["code"] == "06"
    assert kwargs["is_fixable"] is False


def test_report_link_carries_only_the_code_not_the_serial():
    create, _ = _sync("J15A06B4CV030")
    url = create.call_args.kwargs["translation_placeholders"]["report_url"]
    assert url.startswith("https://github.com/saya6k/hacs-xbloom/issues/new?")
    assert "06" in unquote(url)
    assert "B4CV030" not in unquote(url)


def test_report_link_does_not_presume_a_mapped_colour():
    """Any unknown code may be a colour newer than the store list, so the
    pre-filled body never suggests one that already has a code."""
    create, _ = _sync("J15A06B4CV030")
    body = unquote(create.call_args.kwargs["translation_placeholders"]["report_url"])
    for name in ("Sage Green", "Twilight", "Midnight", "Moonlight"):
        assert name not in body


def test_known_codes_clear_the_issue():
    for code in ("01", "02", "03", "04", "05"):
        serial = f"J15A{code}B4CV030"
        create, delete = _sync(serial)
        create.assert_not_called()
        delete.assert_called_once()
        assert delete.call_args.args[1:] == ("xbloom", "unknown_machine_color_e1")


def test_too_short_a_serial_raises_nothing():
    create, delete = _sync("J15")
    create.assert_not_called()
    delete.assert_called_once()


def test_issue_text_exists_in_every_translation():
    import json
    from pathlib import Path

    base = Path(connection.__file__).resolve().parent.parent
    for path in (base / "strings.json", *sorted((base / "translations").glob("*.json"))):
        issue = json.loads(path.read_text())["issues"]["unknown_machine_color"]
        assert "{code}" in issue["description"] and "{report_url}" in issue["description"], path
