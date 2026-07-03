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
import re
import time
from urllib.parse import parse_qs, urlparse

import aiohttp
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_pem_public_key

_LOGGER = logging.getLogger(__name__)

API_BASE = "https://client-api.xbloom.com"
SHARE_BASE = "https://share-h5.xbloom.com"

# A separate, newer public "Coffee Recipe Hub" web frontend
# (collective.xbloom.com) and its own backend (collective-api.xbloom.com) —
# unrelated to API_BASE/client-api.xbloom.com, discovered by reading its
# React bundle (2026-07-03; live-verified: POST communityRecipe/recipe/detail
# {"id": <int>, "type": 1} -> {"code": 200, "data": {..., "shareRecipeLink":
# "https://share-h5.xbloom.com/?id=..."}}, no auth required). We only use it
# to resolve a collective.xbloom.com/recipe/{id} link to its equivalent
# share-h5.xbloom.com link, then hand off to the already-verified
# RecipeDetail.html path below — avoids a second translation function for a
# response shape that differs subtly (e.g. cupType comes back as a string
# there, not the int RecipeDetail.html/cloud_recipe_to_local expects). The
# same collective-api.xbloom.com backend also powers the hub's search box
# (POST communityRecipe/index/page) and its filter dropdowns (POST
# communityRecipe/recipe/criteria, returning name<->id lookup tables) — see
# :meth:`XBloomCloudClient.search_collective_recipes`.
COLLECTIVE_API_BASE = "https://collective-api.xbloom.com"
_COLLECTIVE_RECIPE_URL_RE = re.compile(r"collective\.xbloom\.com/recipe/(\d+)")

# Search request field mappings, confirmed live (2026-07-03) by reading the
# collective.xbloom.com React bundle's search-request builder.
_COLLECTIVE_CATEGORY = {"coffee": 1, "tea": 2}
_COLLECTIVE_SRC = {"official": 1, "user": 2}
_COLLECTIVE_SORT_FIELD = {"date": 1, "likes": 2, "downloads": 3}
_COLLECTIVE_SORT_DIRECTION = {"asc": 1, "desc": 2}


def _resolve_criteria_values(
    names: list[str] | None, facet_list: list[dict]
) -> tuple[list[str], list[str]]:
    """Case-insensitive match of user-provided ``names`` against one
    criteria facet's ``[{"name": ..., "value": ...}]`` list. Returns
    ``(resolved_values, unmatched_names)`` — unmatched names are reported
    back rather than silently dropped, so the caller can tell the user."""
    if not names:
        return [], []
    by_name = {str(item["name"]).strip().lower(): item["value"] for item in facet_list}
    resolved: list[str] = []
    unmatched: list[str] = []
    for name in names:
        value = by_name.get(str(name).strip().lower())
        if value is not None:
            resolved.append(value)
        else:
            unmatched.append(name)
    return resolved, unmatched


def _collective_result_to_summary(item: dict, roast_names: dict[str, str]) -> dict:
    """Reshape one raw collective-hub search result row into a smaller,
    stable summary for services/LLM tools. ``roast_names`` maps the
    criteria roastList's ``value`` -> ``name`` (the result row's own
    ``roast`` field is just the numeric id, unlike origin/varietal/
    process/flavor which come back as readable name strings already)."""
    roast_id = item.get("roast")
    return {
        "community_recipe_id": item.get("communityRecipeId"),
        "name": item.get("recipeName"),
        "official": bool(item.get("official")),
        "user_name": item.get("userName"),
        "machine": item.get("model"),
        "cup_type": item.get("cupType"),
        "dose_g": item.get("dose"),
        "ratio": item.get("grandWater"),
        "pour_count": item.get("pourCount"),
        "total_water_ml": item.get("volume"),
        "likes_count": item.get("likesCount"),
        "origin": item.get("origin") or [],
        "varietal": item.get("varietal") or [],
        "process": item.get("process") or [],
        "roast": roast_names.get(str(roast_id)) if roast_id is not None else None,
        "flavor": item.get("flavor") or [],
        "share_url": item.get("shareRecipeLink"),
    }

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


def _local_pour_to_cloud(p: dict, index: int) -> dict:
    before, after = _local_vibration_to_cloud(p.get("vibration"))
    return {
        # Required by the wire API — a pour object missing theName is
        # rejected wholesale ("Les données de versement de cette recette
        # sont anormales" / abnormal pour data). Naming derived purely by
        # position, matching the reference implementation's buildPourList
        # verbatim: first pour is always "Bloom", subsequent ones are
        # "Pour {index+1}" (so the 2nd pour is "Pour 2", not "Pour 1" —
        # confirmed against xbloom-agent's raw index.ts).
        "theName": "Bloom" if index == 0 else f"Pour {index + 1}",
        "volume": p.get("volume_ml", 30),
        "temperature": p.get("temperature_c", 93),
        "flowRate": p.get("flow_rate", 3.0),
        "pausing": p.get("pause_seconds", 0),
        "pattern": _LOCAL_PATTERN_TO_CLOUD.get(int(p.get("pattern", 2)), 2),
        "isEnableVibrationBefore": before,
        "isEnableVibrationAfter": after,
    }


# Tolerance for the float rounding that can creep in through dose_g*ratio
# vs. summed integer pour_ml volumes.
_POUR_VOLUME_TOLERANCE_ML = 1.0


def validate_pour_volume_consistency(recipe: dict) -> str | None:
    """Check a wire-level constraint confirmed via live testing (2026-07-03):
    for a dosed (coffee-style) recipe, ``sum(pours[].volume_ml) +
    bypass_volume`` must equal ``dose_g * ratio`` (the declared total water
    budget) — ``tuRecipeAdd.tuhtml``/``tuRecipeUpdate.tuhtml`` silently
    reject a mismatch with a generic, French, unactionable
    ``{"result": "fail", "info": "Les données de versement de cette
    recette sont anormales"}`` (abnormal pour data). This isn't documented
    anywhere in the reference implementation — confirmed empirically by
    bisecting a failing live create call.

    Returns ``None`` if the recipe satisfies the constraint, or a
    human-readable mismatch description otherwise. Zero-dose/no-ratio
    recipes (tea) have no declared total to check against, so the
    constraint doesn't apply to them.
    """
    dose_g = float(recipe.get("dose_g", 0) or 0)
    ratio = recipe.get("ratio")
    if dose_g <= 0 or not ratio:
        return None
    total_water = dose_g * float(ratio)
    pour_sum = sum(float(p.get("volume_ml", 0)) for p in recipe.get("pours", []))
    bypass_volume = float(recipe.get("bypass_volume", 0) or 0)
    combined = pour_sum + bypass_volume
    if abs(combined - total_water) > _POUR_VOLUME_TOLERANCE_ML:
        return (
            f"pour volumes ({pour_sum:g} ml) + bypass_volume "
            f"({bypass_volume:g} ml) = {combined:g} ml, but dose_g * ratio "
            f"= {total_water:g} ml — the XBloom cloud API requires these "
            "to match. Adjust the pours, bypass_volume, dose_g, or ratio "
            "so they add up."
        )
    return None


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
    pour_list = [_local_pour_to_cloud(p, i) for i, p in enumerate(local.get("pours", []))]
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
        # Cached for the lifetime of this client — the collective hub's
        # filter lookup tables (origin/varietal/process/roast/flavor/
        # machine/cupType name<->id maps) change rarely enough that
        # re-fetching on every search call would be wasteful.
        self._collective_criteria: dict | None = None

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

    async def _post_collective(self, endpoint: str, body: object) -> dict | None:
        """POST to collective-api.xbloom.com — a separate, unauthenticated
        API from ``API_BASE`` above (see ``COLLECTIVE_API_BASE``'s
        module-level comment). Returns ``None`` on any failure, never
        raises."""
        try:
            async with self._session.post(
                f"{COLLECTIVE_API_BASE}/{endpoint}",
                json=body,
                headers=_HEADERS,
                timeout=_TIMEOUT,
            ) as resp:
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            _LOGGER.warning("XBloom collective-api call to %s failed: %s", endpoint, exc)
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

    async def _resolve_collective_link(self, community_recipe_id: str) -> str | None:
        """Resolve a collective.xbloom.com/recipe/{id} link to its
        share-h5.xbloom.com share link, via the separate collective-api.xbloom.com
        backend (see the module-level comment by ``COLLECTIVE_API_BASE``).
        Returns ``None`` on any failure — never raises.
        """
        body = await self._post_collective(
            "communityRecipe/recipe/detail",
            {"id": int(community_recipe_id), "type": 1},
        )
        if not body or body.get("code") != 200:
            return None
        return (body.get("data") or {}).get("shareRecipeLink")

    async def _fetch_collective_criteria(self) -> dict | None:
        """Fetch (and cache) the collective hub's filter lookup tables —
        ``{"originList": [{"name": ..., "value": ...}], "varietalList": [...],
        "processingList": [...], "roastList": [...], "flavorList": [...],
        "machineList": [...], "cupTypeList": [...]}`` — used by
        :meth:`search_collective_recipes` to resolve free-text filter names
        into the ids the wire API expects. No auth required. Returns
        ``None`` on any failure — never raises.
        """
        if self._collective_criteria is not None:
            return self._collective_criteria
        body = await self._post_collective("communityRecipe/recipe/criteria", {})
        if not body or body.get("code") != 200:
            return None
        self._collective_criteria = body.get("data") or {}
        return self._collective_criteria

    async def search_collective_recipes(
        self,
        keyword: str | None = None,
        category: str | None = None,
        src: str | None = None,
        machine: list[str] | None = None,
        cup_type: list[str] | None = None,
        origin: list[str] | None = None,
        varietal: list[str] | None = None,
        process: list[str] | None = None,
        roast: list[str] | None = None,
        flavor: list[str] | None = None,
        sort: str = "likes",
        sort_direction: str = "desc",
        page: int = 1,
        page_size: int = 10,
    ) -> dict | None:
        """Search the public collective.xbloom.com community recipe hub.

        No login required — a completely separate, unauthenticated API
        from the rest of this class (which acts on the user's own private
        cloud account). ``machine``/``cup_type``/``origin``/``varietal``/
        ``process``/``roast``/``flavor`` accept free-text names (e.g.
        ``["Ethiopia"]``, ``["Dark Roast"]``), resolved case-insensitively
        against :meth:`_fetch_collective_criteria`'s live lookup tables
        rather than hardcoded here (the hub has ~28 origins / ~49
        varietals / ~93 flavors — not worth embedding as static enums).

        Returns ``None`` on any network/parse failure. On success, a dict
        with ``list`` (translated result rows, see
        :func:`_collective_result_to_summary`), ``page_index``/
        ``total_page``/``total``, and ``unmatched`` — a ``{facet: [names]}``
        map of any filter names that didn't resolve, for the caller to
        surface back to the user rather than silently dropping them.
        """
        criteria = await self._fetch_collective_criteria()
        if criteria is None:
            return None
        unmatched: dict[str, list[str]] = {}

        def resolve(names: list[str] | None, facet_key: str) -> list[str] | None:
            values, bad = _resolve_criteria_values(names, criteria.get(facet_key) or [])
            if bad:
                unmatched[facet_key] = bad
            return values or None

        payload = {
            "pageIndex": page,
            "pageSize": page_size,
            "keyword": keyword or None,
            "recipeType": _COLLECTIVE_CATEGORY.get((category or "").lower()),
            "recipeUserType": _COLLECTIVE_SRC.get((src or "").lower()),
            "sort": _COLLECTIVE_SORT_FIELD.get((sort or "likes").lower(), 2),
            "sortType": _COLLECTIVE_SORT_DIRECTION.get((sort_direction or "desc").lower(), 2),
            "originIds": resolve(origin, "originList"),
            "varietalIds": resolve(varietal, "varietalList"),
            "processIds": resolve(process, "processingList"),
            "roastList": resolve(roast, "roastList"),
            "flavorIds": resolve(flavor, "flavorList"),
            "machineList": resolve(machine, "machineList"),
            "cupTypeList": resolve(cup_type, "cupTypeList"),
        }
        body = await self._post_collective("communityRecipe/index/page", payload)
        if not body or body.get("code") != 200:
            return None
        data = body.get("data") or {}
        roast_names = {
            str(item["value"]): item["name"] for item in (criteria.get("roastList") or [])
        }
        results = [
            _collective_result_to_summary(item, roast_names)
            for item in (data.get("list") or [])
        ]
        return {
            "list": results,
            "page_index": data.get("pageIndex"),
            "total_page": data.get("totalPage"),
            "total": data.get("total"),
            "unmatched": unmatched,
        }

    async def fetch_official_recipes(self, limit: int = 20) -> list[dict] | None:
        """Fetch the top ``limit`` official recipes (by likes) from the
        public collective hub, each translated to a full
        ``RECIPE_SCHEMA``-shaped dict.

        :meth:`search_collective_recipes` only returns per-recipe
        *summaries* (no ``pours``) — the hub's list/search endpoint doesn't
        include them — so each result needs its own
        :meth:`fetch_shared_recipe` round-trip for the full recipe.
        ``limit`` bounds how many of those extra round-trips this makes,
        since the caller runs unattended at startup (see
        ``coordinator.async_seed_recipes``). Returns ``None`` only
        if the initial search itself fails (e.g. no network) — an
        individual recipe's detail fetch failing is skipped, not fatal.
        """
        search = await self.search_collective_recipes(
            src="official", sort="likes", sort_direction="desc",
            page_size=max(1, limit),
        )
        if search is None:
            return None
        recipes: list[dict] = []
        for item in search["list"][:limit]:
            share_url = item.get("share_url")
            if not share_url:
                continue
            detail = await self.fetch_shared_recipe(share_url)
            if detail is not None:
                recipes.append(detail)
        return recipes

    async def fetch_shared_recipe(self, share_url_or_id: str) -> dict | None:
        """Fetch a recipe by share URL, collective.xbloom.com/recipe/{id}
        URL, or bare share id. No login required.

        Returns a dict shaped for ``schema.RECIPE_SCHEMA``, or ``None`` if
        the id can't be parsed or the API call fails/returns not-found.
        """
        value = share_url_or_id.strip()
        collective_match = _COLLECTIVE_RECIPE_URL_RE.search(value)
        if collective_match:
            resolved = await self._resolve_collective_link(collective_match.group(1))
            if not resolved:
                return None
            value = resolved
        share_id = _parse_share_id(value)
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
        On success returns ``{"table_id": int, "share_url": str}``.

        The API's create response only returns ``tableId`` — no share
        link. The reference implementation guesses one client-side
        (``btoa(String(tableId))``), but live testing (2026-07-03) proved
        that guess does NOT resolve via :meth:`fetch_shared_recipe`: a
        real account's ``shareRecipeLink`` decodes to 16 bytes of opaque
        binary, not the ASCII digits of a table id — it's server-assigned,
        not derivable. So this reads the real link back via
        :meth:`get_recipe` right after creating. ``share_url`` is ``""``
        if that follow-up lookup doesn't find it (e.g. list eventual
        consistency) — never a guessed value that's confirmed broken.
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
            _LOGGER.warning(
                "XBloom cloud create_recipe rejected: %s",
                (resp or {}).get("info", "no response"),
            )
            return None
        table_id = resp.get("tableId")
        if table_id is None:
            return None
        created_raw = await self.get_recipe(table_id)
        share_url = (created_raw or {}).get("shareRecipeLink") or ""
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
        (:meth:`XBloomCoordinator.async_export_recipe`) is responsible
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
        ok = bool(resp and resp.get("result") == "success")
        if not ok:
            _LOGGER.warning(
                "XBloom cloud update_recipe rejected: %s",
                (resp or {}).get("info", "no response"),
            )
        return ok

    async def delete_recipe(self, table_id: int) -> bool:
        """Delete a recipe from the logged-in account.

        Requires a prior successful login. Returns ``False`` on any
        failure — never raises. Live testing (2026-07-03) found the
        wire API is idempotent for a ``table_id`` that *was* a valid
        recipe on this account: deleting it again after it's already
        gone still returns success. A ``table_id`` that never existed
        on the account at all returns ``False``. Either way this method
        never raises.
        """
        if not self.logged_in:
            return False
        payload = {**_auth_base(self.member_id, self.token), "tableId": table_id}
        resp = await self._post_encrypted("tuRecipeDelete.tuhtml", payload)
        return bool(resp and resp.get("result") == "success")
