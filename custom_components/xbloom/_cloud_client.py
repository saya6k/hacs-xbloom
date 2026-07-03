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
import time
from urllib.parse import parse_qs, quote, urlparse

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

# Spread into every authenticated call after login — verified verbatim
# against the reference source's authBase(). See tasks/plan.md "Verified
# facts".
_AUTH_INTERFACE_VERSION = 20240918
_AUTH_SKEY = "testskey"


def _auth_base(member_id: int, token: str) -> dict:
    return {
        "interfaceVersion": _AUTH_INTERFACE_VERSION,
        "skey": _AUTH_SKEY,
        "phoneType": "Android",
        "memberId": member_id,
        "clientType": 2,
        "languageType": 1,
        "token": token,
    }


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


# Local pattern int -> cloud pattern int. Inverse of _CLOUD_PATTERN_TO_LOCAL,
# built directly against the local int numbering pinned by the vendored
# PourPattern enum (center=0, circular=1, spiral=2 — see coordinator.py's
# POUR_PATTERN_OPTIONS / schema.py's _PATTERN_NAME_TO_INT): center(0)->
# centered(1), circular(1)->circular(3), spiral(2)->spiral(2).
_LOCAL_PATTERN_TO_CLOUD = {0: 1, 1: 3, 2: 2}

# Inverse of _CLOUD_CUP_TYPE_TO_LOCAL.
_LOCAL_CUP_TYPE_TO_CLOUD = {v: k for k, v in _CLOUD_CUP_TYPE_TO_LOCAL.items()}

# Static fields the reference implementation always sends on create,
# independent of the recipe's own data. Verified verbatim against the raw
# denull0/xbloom-agent source (tuRecipeAdd.tuhtml payload shape) — see
# tasks/plan.md "Verified facts".
_CREATE_STATIC_FIELDS = {
    "adaptedModel": 1,
    "theSubsetId": 0,
    "subSetType": 2,
    "appPlace": [4],
    "isShortcuts": 2,
}


def _local_vibration_to_cloud(vibration: object) -> tuple[int, int]:
    """Local single ``vibration`` enum (none/before/after/both) -> cloud's
    two isEnableVibrationBefore/After ints (1=on, 2=off)."""
    v = str(vibration or "none")
    before = v in ("before", "both")
    after = v in ("after", "both")
    return (1 if before else 2, 1 if after else 2)


def _local_pour_to_cloud(p: dict) -> dict:
    before, after = _local_vibration_to_cloud(p.get("vibration"))
    return {
        "volume": p.get("volume_ml", 30),
        "temperature": p.get("temperature_c", 93),
        "flowRate": p.get("flow_rate", 3.0),
        "pausing": p.get("pause_seconds", 0),
        "pattern": _LOCAL_PATTERN_TO_CLOUD.get(int(p.get("pattern", 2)), 2),
        "isEnableVibrationBefore": before,
        "isEnableVibrationAfter": after,
    }


def local_recipe_to_cloud(local: dict) -> dict:
    """Translate a ``RECIPE_SCHEMA``-validated local recipe dict into the
    recipe-specific fields of the ``tuRecipeAdd.tuhtml`` create payload.

    Inverse of :func:`cloud_recipe_to_local`. Caller
    (:meth:`XBloomCloudClient.create_recipe`) adds ``authBase`` plus the
    create call's static fields (see ``_CREATE_STATIC_FIELDS``) — this only
    reshapes the recipe's own data.
    """
    bypass_volume = float(local.get("bypass_volume", 0) or 0)
    bypass_temperature = float(local.get("bypass_temperature", 0) or 0)
    grind_size = int(local.get("grind_size", 0) or 0)
    pour_list = [_local_pour_to_cloud(p) for p in local.get("pours", [])]
    return {
        "theName": local["name"],
        "dose": local.get("dose_g", 0) or 0,
        "grandWater": local.get("ratio"),
        "grinderSize": grind_size,
        "rpm": local.get("rpm", 80),
        "cupType": _LOCAL_CUP_TYPE_TO_CLOUD.get(str(local.get("cup_type", "omni_dripper")), 2),
        "bypassTemp": bypass_temperature,
        "bypassVolume": bypass_volume,
        "isSetGrinderSize": 1 if grind_size > 0 else 2,
        "isEnableBypassWater": 1 if (bypass_volume > 0 or bypass_temperature > 0) else 2,
        "pourDataJSONStr": json.dumps(pour_list),
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

    async def _post(self, endpoint: str, body: object) -> dict | None:
        try:
            async with self._session.post(
                f"{API_BASE}/{endpoint}", json=body, headers=_HEADERS, timeout=_TIMEOUT,
            ) as resp:
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            _LOGGER.warning("XBloom cloud call to %s failed: %s", endpoint, exc)
            return None

    async def _post_plain(self, endpoint: str, payload: dict) -> dict | None:
        return await self._post(endpoint, payload)

    async def _post_encrypted(self, endpoint: str, payload: dict) -> dict | None:
        """Authenticated call — the whole payload is RSA-chunk-encrypted and
        sent as a JSON-encoded *string* body (matching the reference
        ``postEncrypted``: ``body: JSON.stringify(encrypted)`` where
        ``encrypted`` is itself the base64 ciphertext string, not an
        object wrapping it)."""
        return await self._post(endpoint, _rsa_encrypt(payload))

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

    async def list_recipes(self) -> list[dict] | None:
        """List every recipe on the logged-in account.

        Wraps ``tuMyTeaRecipeCreated.tuhtml`` (the literal endpoint name
        used for listing *all* recipe types, not just tea — see
        tasks/plan.md "Verified facts"). Requires a prior successful
        :meth:`login`; returns ``None`` if not logged in or the call
        fails — never raises. Each list entry is the raw cloud shape
        (``tableId``, ``theName``, ``dose``, ``grandWater``,
        ``grinderSize``, ``rpm``, ``shareRecipeLink``, ``pourList``, ...).
        """
        if not self.logged_in:
            return None
        payload = {
            **_auth_base(self.member_id, self.token),
            "pageNumber": 1,
            "countPerPage": 100,
            "adaptedModel": 1,
        }
        resp = await self._post_encrypted("tuMyTeaRecipeCreated.tuhtml", payload)
        if not resp or resp.get("result") != "success":
            return None
        return resp.get("list") or []

    async def create_recipe(self, local_recipe: dict) -> dict | None:
        """Create a new recipe on the logged-in account.

        ``local_recipe`` is a ``RECIPE_SCHEMA``-validated dict (same shape
        as a saved local recipe). Requires a prior successful :meth:`login`;
        returns ``None`` if not logged in or the call fails — never raises.
        On success returns ``{"table_id": int, "share_url": str}`` — the
        share id/URL are derived client-side the same way the reference
        implementation does (``btoa(String(tableId))``), not returned by
        the API itself.
        """
        if not self.logged_in:
            return None
        payload = {
            **_auth_base(self.member_id, self.token),
            **local_recipe_to_cloud(local_recipe),
            **_CREATE_STATIC_FIELDS,
            "theColor": "",
            "createTimeStamp": int(time.time() * 1000),
        }
        resp = await self._post_encrypted("tuRecipeAdd.tuhtml", payload)
        if not resp or resp.get("result") != "success":
            return None
        table_id = resp.get("tableId")
        if table_id is None:
            return None
        share_id = base64.b64encode(str(table_id).encode("ascii")).decode("ascii")
        share_url = f"{SHARE_BASE}/?id={quote(share_id, safe='')}"
        return {"table_id": table_id, "share_url": share_url}

    async def get_recipe(self, table_id: int) -> dict | None:
        """Fetch one recipe's current raw cloud-shape dict by ``tableId``.

        The wire API has no single-recipe authenticated fetch, so this
        lists every recipe on the account (:meth:`list_recipes`) and
        matches by ``tableId`` — the same approach the reference
        implementation uses before an edit. Returns ``None`` if not
        logged in, the call fails, or no recipe matches.
        """
        recipes = await self.list_recipes()
        if recipes is None:
            return None
        for r in recipes:
            if r.get("tableId") == table_id:
                return r
        return None

    async def update_recipe(self, table_id: int, cloud_fields: dict) -> bool:
        """Send a full-replace update for an existing recipe.

        ``cloud_fields`` must already be a complete cloud-shape payload —
        the wire API is full-replace, not a merge patch, so the caller
        (:meth:`XBloomCoordinator.async_edit_cloud_recipe`) is responsible
        for filling in every unchanged field from the recipe's current
        state first (via :meth:`get_recipe`). Requires a prior successful
        login. Returns ``False`` on any failure — never raises.
        """
        if not self.logged_in:
            return False
        payload = {
            **_auth_base(self.member_id, self.token),
            **cloud_fields,
            "tableId": table_id,
        }
        resp = await self._post_encrypted("tuRecipeUpdate.tuhtml", payload)
        return bool(resp and resp.get("result") == "success")

    async def delete_recipe(self, table_id: int) -> bool:
        """Delete a recipe from the logged-in account.

        Requires a prior successful login. Returns ``False`` on any
        failure — never raises. The wire API has no distinguishable
        "not found" result (see tasks/plan.md "Verified facts"), so a
        nonexistent/already-deleted ``table_id`` also just returns
        ``False`` rather than a specific error.
        """
        if not self.logged_in:
            return False
        payload = {**_auth_base(self.member_id, self.token), "tableId": table_id}
        resp = await self._post_encrypted("tuRecipeDelete.tuhtml", payload)
        return bool(resp and resp.get("result") == "success")
