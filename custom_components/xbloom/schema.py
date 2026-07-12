"""YAML / options recipe schemas.

Lifted out of ``__init__.py`` so ``config_flow.py``'s OptionsFlow can
validate recipes coming from the UI without re-importing the package
root (which would create a circular import during config-flow setup).
"""
from __future__ import annotations

import hashlib
from urllib.parse import parse_qs, unquote, urlparse
from uuid import uuid4

import voluptuous as vol

import homeassistant.helpers.config_validation as cv

_PATTERN_NAME_TO_INT = {"center": 0, "circular": 1, "spiral": 2}


def _coerce_pour_pattern(value):
    """Accept either the int (0/1/2) or the name (center/circular/spiral)."""
    if isinstance(value, bool):
        raise vol.Invalid(f"pattern must be a string or int (got {value!r})")
    if isinstance(value, int):
        if value in (0, 1, 2):
            return value
        raise vol.Invalid(f"pattern int must be 0, 1, or 2 (got {value})")
    if isinstance(value, str):
        key = value.strip().lower()
        if key in _PATTERN_NAME_TO_INT:
            return _PATTERN_NAME_TO_INT[key]
        raise vol.Invalid(
            f"pattern must be one of {list(_PATTERN_NAME_TO_INT)} (got {value!r})"
        )
    raise vol.Invalid(f"pattern must be a string or int (got {type(value).__name__})")


POUR_SCHEMA = vol.Schema(
    {
        vol.Required("volume_ml"): cv.positive_int,
        vol.Required("temperature_c"): cv.positive_int,
        vol.Optional("flow_rate", default=3.0): vol.Coerce(float),
        vol.Optional("pause_seconds", default=0): vol.Coerce(int),
        vol.Optional("pattern", default=2): _coerce_pour_pattern,
        vol.Optional("vibration", default="none"): vol.In(
            ["none", "before", "after", "both"]
        ),
    }
)

RECIPE_SCHEMA = vol.Schema(
    {
        # Local-store metadata (all optional — absent on YAML input, filled
        # in by the recipe store). `uid` is the stable local identity;
        # `cloud_table_id`/`share_url` coexist with it once a recipe has
        # been exported to / imported from the XBloom cloud. None of these
        # affect brewing (`coordinator._build_recipe_from_yaml` only reads
        # the brew fields below).
        vol.Optional("uid"): cv.string,
        vol.Optional("cloud_table_id"): vol.Coerce(int),
        vol.Optional("share_url"): cv.string,
        vol.Optional("source"): cv.string,
        vol.Required("name"): cv.string,
        vol.Optional("grind_size", default=50): vol.Coerce(int),
        vol.Optional("rpm", default=80): vol.Coerce(int),
        vol.Optional("dose_g", default=15.0): vol.Coerce(float),
        # Water ratio (total water = dose_g * ratio), matching the XBloom
        # cloud API's dose/grandWater pair. Optional/None for zero-dose
        # (tea) recipes, where ratio is meaningless — total water is then
        # derived from the sum of pour volumes (see compute_total_water_ml).
        vol.Optional("ratio", default=None): vol.Any(None, vol.Coerce(float)),
        vol.Optional("cup_type", default="omni_dripper"): cv.string,
        vol.Optional("bypass_volume", default=0): vol.Coerce(float),
        vol.Optional("bypass_temperature", default=0): vol.Coerce(float),
        vol.Required("pours"): [POUR_SCHEMA],
    }
)


RECIPE_PROTECTED_FIELDS = ("uid", "cloud_table_id", "share_url", "source")


def strip_protected_recipe_fields(recipe: dict) -> dict:
    """Drop system-managed identity/cloud-metadata fields from
    user-supplied recipe input (create_recipe's YAML, edit_recipe's
    changes YAML).

    ``uid``/``cloud_table_id``/``share_url``/``source`` are assigned only
    by create/import/export — never by user input — so a raw YAML blob
    can't spoof another recipe's identity or point cloud_export_recipe at
    a cloud_table_id it doesn't own. Returns a new dict; ``recipe`` is not
    mutated.
    """
    return {k: v for k, v in recipe.items() if k not in RECIPE_PROTECTED_FIELDS}


def new_recipe_uid() -> str:
    """Mint a local recipe uid (12 hex chars, distinct from cloud ids)."""
    return uuid4().hex[:12]


def yaml_recipe_uid(name: str) -> str:
    """Deterministic uid for a configuration.yaml recipe.

    YAML recipes are re-loaded from scratch every HA start, so a random
    uid would change each boot; deriving it from the name keeps it stable.
    """
    return "yaml-" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]


def share_id_of(url_or_id: str) -> str | None:
    """Normalize a share URL or bare share id to the decoded id string.

    ``https://share-h5.xbloom.com/?id=Km%2FJcq%3D%3D`` and the bare
    (possibly percent-encoded) id both normalize to the same decoded
    string, so stored ``share_url`` values and user input compare equal.
    Returns None for URLs without an ``id`` query parameter (e.g.
    collective.xbloom.com links — those identify recipes by a different,
    unstored id space).
    """
    s = url_or_id.strip()
    if "://" in s:
        vals = parse_qs(urlparse(s).query).get("id")
        return vals[0] if vals else None
    return unquote(s) or None


def find_recipe(recipes: dict, identifier: str) -> tuple[str, dict] | None:
    """Resolve a cross-identifier to a ``(name, recipe)`` pair.

    Accepts, in priority order: local ``uid``, cloud ``cloud_table_id``
    (integer), share URL / share id (matched against stored
    ``share_url``), and finally the exact recipe name. Returns None when
    nothing matches — callers decide whether that means auto-import or
    an error.
    """
    identifier = str(identifier).strip()
    if not identifier or not recipes:
        return None

    for name, recipe in recipes.items():
        if isinstance(recipe, dict) and recipe.get("uid") == identifier:
            return name, recipe

    try:
        table_id = int(identifier)
    except ValueError:
        table_id = None
    if table_id is not None:
        for name, recipe in recipes.items():
            if isinstance(recipe, dict) and recipe.get("cloud_table_id") == table_id:
                return name, recipe

    share_id = share_id_of(identifier)
    if share_id:
        for name, recipe in recipes.items():
            if not isinstance(recipe, dict):
                continue
            stored = recipe.get("share_url")
            if stored and share_id_of(stored) == share_id:
                return name, recipe

    recipe = recipes.get(identifier)
    if isinstance(recipe, dict):
        return identifier, recipe
    return None


def dedupe_name(name: str, existing) -> str:
    """Return ``name``, or ``name (2)`` / ``name (3)`` … if already taken."""
    if name not in existing:
        return name
    n = 2
    while f"{name} ({n})" in existing:
        n += 1
    return f"{name} ({n})"


def scale_pours_to_total(pours: list, target_total_ml: float) -> list:
    """Proportionally rescale pour volumes to sum to ``target_total_ml``.

    Used when an execute-time ``dose_g``/``ratio`` override changes the
    total brew water: the cloud API's invariant (and the machine's
    expectation) is ``sum(pours) + bypass == dose_g * ratio``, so the
    recipe's pours are rescaled for that one brew. Each volume is rounded
    to a whole ml; the rounding residue is absorbed by the last pour so
    the sum is exact. Returns new dicts (inputs are not mutated). Pours
    with a zero/degenerate current total are returned unchanged.
    """
    if not pours:
        return []
    current_total = sum(float(p.get("volume_ml", 0)) for p in pours)
    if current_total <= 0 or target_total_ml <= 0:
        return [dict(p) for p in pours]
    factor = float(target_total_ml) / current_total
    scaled = [dict(p) for p in pours]
    running = 0
    for p in scaled[:-1]:
        p["volume_ml"] = max(1, round(float(p.get("volume_ml", 0)) * factor))
        running += p["volume_ml"]
    scaled[-1]["volume_ml"] = max(1, round(target_total_ml) - running)
    return scaled


def compute_total_water_ml(recipe: dict) -> float:
    """Total brew water in ml: ``dose_g * ratio`` when both are set.

    Falls back to summing pour volumes when ``ratio`` is omitted or
    ``dose_g`` is 0 (tea recipes have no weighed dose, so ratio is
    undefined) — this mirrors the pre-``ratio`` behaviour where a missing
    ``total_water`` was derived from the pours. Shared by
    ``coordinator._build_recipe_from_yaml`` (what the machine actually
    brews) and ``llm/recipe.py`` (what we tell the user/LLM it will
    brew) so the two can't drift apart.
    """
    dose_g = float(recipe.get("dose_g", 0) or 0)
    ratio = recipe.get("ratio")
    if dose_g > 0 and ratio:
        return dose_g * float(ratio)
    return sum(float(p.get("volume_ml", 0)) for p in recipe.get("pours", []))
