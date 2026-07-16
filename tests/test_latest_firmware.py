"""Tests for _cloud_client._parse_latest_firmware_response.

The "real response" fixture below is the literal response captured live
from POST https://client-api.xbloom.com/tUpToDateFirmwareVersion.thtml
(2026-07-16) — see _cloud_client.get_latest_firmware()'s docstring. Its
md5 matched cryptofishbug/xbloom-recipe-cli's bundled V12.0D.500 firmware
file byte-for-byte.
"""
from __future__ import annotations

from datetime import datetime, timezone

from custom_components.xbloom._cloud_client import _parse_latest_firmware_response

_REAL_RESPONSE = {
    "data": (
        '{"is_force_upgrade":"N","version_id":85,"version_string":"V12.0D.500",'
        '"content":"1. Added offline functionality in the app<br/>\\n'
        '2. Optimized machine operation logic<br/>\\n3. Improved scale performance<br/>\\n'
        '4. Refined error notification messages<br/>\\n5. Fixed existing bugs",'
        '"md5_string":"5E351B943FA5DA82BA40DE4ADF740259","publishTimestamp":1760025600000,'
        '"contentCn":"placeholder",'
        '"link_url":"https://tbdprodpic.s3.us-east-1.amazonaws.com/20251010/68e8aa51c0b9e.bin"}'
    ),
    "info": "Operation Successful",
    "isForceUpgrade": 2,
    "md5_string": "5E351B943FA5DA82BA40DE4ADF740259",
    "resourceLinks": "https://tbdprodpic.s3.us-east-1.amazonaws.com/20251010/68e8aa51c0b9e.bin",
    "result": "success",
    "theVersion": "V12.0D.500",
}


def test_parses_real_captured_response():
    parsed = _parse_latest_firmware_response(_REAL_RESPONSE)
    assert parsed["version"] == "V12.0D.500"
    assert parsed["md5"] == "5E351B943FA5DA82BA40DE4ADF740259"
    assert parsed["download_url"].endswith("68e8aa51c0b9e.bin")
    assert parsed["force_upgrade"] is False
    assert parsed["published"] == datetime(2025, 10, 9, 16, 0, tzinfo=timezone.utc)
    assert parsed["release_notes"].splitlines()[0] == "1. Added offline functionality in the app"
    assert "<br/>" not in parsed["release_notes"]


def test_returns_none_on_failed_result():
    assert _parse_latest_firmware_response({"result": "fail"}) is None
    assert _parse_latest_firmware_response(None) is None


def test_returns_none_on_unparseable_data_field():
    assert _parse_latest_firmware_response({"result": "success", "data": "not json"}) is None


def test_returns_none_when_version_string_missing():
    resp = {"result": "success", "data": '{"content": "no version here"}'}
    assert _parse_latest_firmware_response(resp) is None


def test_force_upgrade_y_parses_true():
    resp = {
        "result": "success",
        "data": '{"version_string":"V12.0D.600","is_force_upgrade":"Y"}',
    }
    parsed = _parse_latest_firmware_response(resp)
    assert parsed["force_upgrade"] is True
