"""HTTP client for the XBloom cloud account API (recipe sync).

Separate from the vendored ``src/xbloom`` / ``src/xbloom-ble`` BLE
libraries — this talks to XBloom's own cloud REST API over HTTPS, the
same one the official iOS app uses to store/share recipes. Endpoint
paths, payload shapes, and the RSA public key below were confirmed by
reading the *raw source* of the reference MCP server
`denull0/xbloom-agent` (not a summarized/AI-mediated fetch — cryptographic
material specifically was cross-checked against the literal file content).

No login is required for :meth:`XBloomCloudClient.fetch_shared_recipe` —
only the authenticated list/create/edit/delete calls (added in a later
phase) need :meth:`XBloomCloudClient.login` first.
"""
from __future__ import annotations

import base64
import json
import logging
from urllib.parse import parse_qs, urlparse

import aiohttp
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_pem_public_key

_LOGGER = logging.getLogger(__name__)

API_BASE = "https://client-api.xbloom.com"
SHARE_BASE = "https://share-h5.xbloom.com"

# Verified verbatim against the raw denull0/xbloom-agent source (hutool-style
# RSA-1024, PKCS1v1.5 padding — see module docstring).
_RSA_PUBLIC_KEY_B64 = (
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC4LF40GZ72SdhMyl765K/i4nY5"
    "CPcHz2Q1IKWKZ9S79xmK7G8pUhbVf4EZLvnNF1+9IvOFQUKV5Z7ZNNviqSpnql9"
    "tAT+8+J/He0R7pcirvVSxgdr2i9V/C/gmqAEZ5qVTzRnd3uWdFoKzPdEBxP0Ipor"
    "J1VBbCv90yBSOhVxO+QIDAQAB"
)
_RSA_PUBLIC_KEY_PEM = (
    "-----BEGIN PUBLIC KEY-----\n"
    + "\n".join(
        _RSA_PUBLIC_KEY_B64[i : i + 64]
        for i in range(0, len(_RSA_PUBLIC_KEY_B64), 64)
    )
    + "\n-----END PUBLIC KEY-----\n"
).encode("ascii")

# 128-byte (1024-bit) key - 11 bytes of PKCS1v1.5 padding overhead.
_RSA_CHUNK_SIZE = 117

_HEADERS = {
    "Content-Type": "application/json",
    "Referer": f"{SHARE_BASE}/",
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)",
}

_TIMEOUT = aiohttp.ClientTimeout(total=15)


def _rsa_encrypt(payload: dict) -> str:
    """Hutool-style chunked RSA encryption matching the official app.

    The whole JSON payload is encrypted (not just a password field):
    UTF-8 bytes are split into <=117-byte chunks, each PKCS1v1.5-encrypted
    separately, and the concatenated ciphertext is base64-encoded.
    """
    public_key = load_pem_public_key(_RSA_PUBLIC_KEY_PEM)
    plaintext = json.dumps(payload).encode("utf-8")
    chunks = [
        public_key.encrypt(plaintext[i : i + _RSA_CHUNK_SIZE], padding.PKCS1v15())
        for i in range(0, len(plaintext), _RSA_CHUNK_SIZE)
    ]
    return base64.b64encode(b"".join(chunks)).decode("ascii")


# Cloud pattern int -> local pattern name. Cloud: centered=1, spiral=2,
# circular=3. Local (schema.py / vendored PourPattern): center=0,
# circular=1, spiral=2 — names AND ints differ, never copy the int
# directly. See tasks/plan.md "Verified facts".
_CLOUD_PATTERN_TO_LOCAL = {1: "center", 2: "spiral", 3: "circular"}

# Cloud cupType happens to numerically match the vendored CupType enum
# (both trace back to XBloom's own protocol): 1=x_pod, 2=omni_dripper,
# 3=other, 4=tea.
_CLOUD_CUP_TYPE_TO_LOCAL = {1: "x_pod", 2: "omni_dripper", 3: "other", 4: "tea"}


def _cloud_vibration_to_local(before: object, after: object) -> str:
    """Cloud's two isEnableVibrationBefore/After ints (1=on, 2=off) -> the
    local single ``vibration`` enum (none/before/after/both)."""
    b = before == 1
    a = after == 1
    if b and a:
        return "both"
    if b:
        return "before"
    if a:
        return "after"
    return "none"


def _cloud_pour_to_local(p: dict) -> dict:
    return {
        "volume_ml": int(p.get("volume", 30) or 30),
        "temperature_c": int(p.get("temperature", 93) or 93),
        "flow_rate": float(p.get("flowRate", 3.0) or 3.0),
        "pause_seconds": int(p.get("pausing", 0) or 0),
        "pattern": _CLOUD_PATTERN_TO_LOCAL.get(int(p.get("pattern", 2) or 2), "spiral"),
        "vibration": _cloud_vibration_to_local(
            p.get("isEnableVibrationBefore"), p.get("isEnableVibrationAfter")
        ),
    }


def cloud_recipe_to_local(cloud: dict) -> dict:
    """Translate one cloud recipe object (list/fetch response shape) into
    a dict ready for ``schema.RECIPE_SCHEMA`` validation.

    Caller is responsible for running the result through RECIPE_SCHEMA —
    this only reshapes field names/values, it doesn't validate ranges.
    """
    dose_g = float(cloud.get("dose", 0) or 0)
    ratio_raw = cloud.get("grandWater")
    ratio = float(ratio_raw) if (dose_g > 0 and ratio_raw) else None
    cup_val = int(cloud.get("cupType", 2) or 2)
    pour_list = cloud.get("pourList") or []
    return {
        "name": str(cloud.get("theName") or "Imported Recipe"),
        "grind_size": int(cloud.get("grinderSize", 50) or 0),
        "rpm": int(cloud.get("rpm", 80) or 0),
        "dose_g": dose_g,
        "ratio": ratio,
        "cup_type": _CLOUD_CUP_TYPE_TO_LOCAL.get(cup_val, "other"),
        "bypass_volume": float(cloud.get("bypassVolume", 0) or 0),
        "bypass_temperature": float(cloud.get("bypassTemp", 0) or 0),
        "pours": [_cloud_pour_to_local(p) for p in pour_list],
    }


def _parse_share_id(share_url_or_id: str) -> str:
    """Accept either a bare share id or a full share-h5.xbloom.com URL."""
    value = share_url_or_id.strip()
    if "share-h5.xbloom.com" in value:
        query = urlparse(value).query
        return (parse_qs(query).get("id") or [""])[0]
    return value


class XBloomCloudClient:
    """Thin async wrapper around the XBloom cloud recipe-sync API.

    One instance per config entry, holding the logged-in session (if any).
    Never persists the password — only ``member_id``/``token`` are kept
    in memory for the lifetime of this object; the caller (coordinator)
    owns re-login using its own stored email/password when needed.
    """

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session
        self.member_id: int | None = None
        self.token: str | None = None

    @property
    def logged_in(self) -> bool:
        return self.member_id is not None and self.token is not None

    async def _post_plain(self, endpoint: str, payload: dict) -> dict | None:
        try:
            async with self._session.post(
                f"{API_BASE}/{endpoint}", json=payload, headers=_HEADERS, timeout=_TIMEOUT,
            ) as resp:
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            _LOGGER.warning("XBloom cloud call to %s failed: %s", endpoint, exc)
            return None

    async def login(self, email: str, password: str) -> bool:
        """Log in and cache member_id/token. Returns False on any failure
        (bad credentials, network error) — never raises."""
        resp = await self._post_plain(
            "tMemberLogin.thtml",
            {
                "interfaceVersion": 20240918,
                "skey": "testskey",
                "clientType": 2,
                "phoneType": "Android",
                "languageType": 1,
                "email": email,
                "password": password,
            },
        )
        if not resp or resp.get("result") != "success":
            return False
        member = resp.get("member") or {}
        member_id = member.get("tableId")
        token = resp.get("token")
        if member_id is None or not token:
            return False
        self.member_id = int(member_id)
        self.token = str(token)
        return True

    async def fetch_shared_recipe(self, share_url_or_id: str) -> dict | None:
        """Fetch a recipe by share URL or bare id. No login required.

        Returns a dict shaped for ``schema.RECIPE_SCHEMA``, or ``None`` if
        the id can't be parsed or the API call fails/returns not-found.
        """
        share_id = _parse_share_id(share_url_or_id)
        if not share_id:
            return None
        resp = await self._post_plain(
            "RecipeDetail.html",
            {"tableIdOfRSA": share_id, "interfaceVersion": 19700101, "skey": "testskey"},
        )
        if not resp or resp.get("result") != "success":
            return None
        return cloud_recipe_to_local(resp.get("recipeVo") or {})
