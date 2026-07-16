"""Tests for _cloud_client._backend_api_sign — the request-signing scheme
for BACKEND_API_BASE (https://backend-api.xbloom.com), reverse-engineered
2026-07-16 from the official app's RetrofitManager2 OkHttp interceptor
(``bit32()``: uppercase-hex MD5 of "appId,appSecret,nonce,ts"). Untested
against the live API — this only checks the formula matches what the
decompiled source computes, not that xBloom's server accepts it.
"""
from __future__ import annotations

import hashlib

from custom_components.xbloom._cloud_client import (
    _BACKEND_APP_ID,
    _BACKEND_APP_SECRET,
    _backend_api_sign,
)


def test_sign_matches_manual_md5_formula():
    nonce = "abc123"
    ts = "1700000000"
    expected = hashlib.md5(
        f"{_BACKEND_APP_ID},{_BACKEND_APP_SECRET},{nonce},{ts}".encode("utf-8")
    ).hexdigest().upper()
    assert _backend_api_sign(nonce, ts) == expected


def test_sign_is_uppercase_hex_32_chars():
    sign = _backend_api_sign("some-nonce", "1234567890")
    assert len(sign) == 32
    assert sign == sign.upper()
    assert all(c in "0123456789ABCDEF" for c in sign)


def test_sign_changes_with_nonce_or_ts():
    base = _backend_api_sign("nonce1", "1000")
    assert _backend_api_sign("nonce2", "1000") != base
    assert _backend_api_sign("nonce1", "2000") != base
