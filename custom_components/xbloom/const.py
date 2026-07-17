"""Constants for XBloom integration."""

DOMAIN = "xbloom"

# Config entry keys
CONF_MAC_ADDRESS = "mac_address"
CONF_TELEMETRY_INTERVAL = "telemetry_interval"
CONF_SESSION_TIMEOUT = "session_timeout"
CONF_RECIPES = "recipes"
CONF_WATER_SOURCE = "water_source"   # persisted in entry.options
CONF_MODE = "mode"                   # persisted in entry.options
CONF_WEIGHT_UNIT = "weight_unit"     # persisted in entry.options
CONF_TEMP_UNIT = "temp_unit"         # persisted in entry.options

# One-time recipe seed flags (entry.options). The local recipe store is the
# source of truth; the cloud is only consulted once per install (and once
# more when an account is added later) — see coordinator.async_seed_recipes.
CONF_RECIPES_SEEDED = "recipes_seeded"
CONF_ACCOUNT_RECIPES_SEEDED = "account_recipes_seeded"

# entry.options: what HA last wrote to each Easy Mode slot —
# {"A": {"uid": ..., "name": ...}, ...}. The machine never reports slot
# contents, so this record is the only source for the slot sensor entities.
CONF_EASY_SLOTS = "easy_slots"

# XBloom cloud account — both optional. Absent entirely (not just empty
# strings) when the user skips the account step; cloud-backed services/LLM
# tools must check for their absence and fail gracefully, never assume they
# exist. Stored in entry.data (identity/credentials), not entry.options.
CONF_EMAIL = "email"
CONF_PASSWORD = "password"

# Defaults
DEFAULT_TELEMETRY_INTERVAL = 5  # seconds
DEFAULT_SESSION_TIMEOUT = 60    # seconds
DEFAULT_WATER_SOURCE = 0        # 0 = tank
DEFAULT_MODE = "easy"
DEFAULT_WEIGHT_UNIT = "g"
DEFAULT_TEMP_UNIT = "c"

# Data keys
DATA_COORDINATOR = "coordinator"

# Services
SERVICE_EXECUTE_RECIPE = "execute_recipe"
# Tea recipes take a completely different BLE sequence (brewing.py's
# _async_brew_tea) and none of execute_recipe's coffee-only fields
# (dose/ratio/grind/bypass) apply — a separate, leaner service avoids
# exposing them for a tea brew. Shares ATTR_RECIPE with execute_recipe /
# create_recipe / edit_recipe so recipe targeting stays consistent.
SERVICE_EXECUTE_TEA_RECIPE = "execute_tea_recipe"
ATTR_GRIND_SIZE = "grind_size"
ATTR_RPM = "rpm"
ATTR_DOSE_G = "dose_g"
ATTR_RATIO = "ratio"
ATTR_BYPASS_VOLUME = "bypass_volume"
ATTR_BYPASS_TEMPERATURE = "bypass_temperature"

# Cross-identifier field shared by every recipe-addressing service: accepts
# a local uid, a cloud table id, a share URL/id, or the exact recipe name
# (resolution order in schema.find_recipe).
ATTR_RECIPE = "recipe"

# Local recipe store services — the local store (entry.options[CONF_RECIPES])
# is the source of truth; these never touch the cloud.
SERVICE_LIST_RECIPES = "list_recipes"
ATTR_QUERY = "query"

SERVICE_CREATE_RECIPE = "create_recipe"
ATTR_RECIPE_YAML = "recipe_yaml"

SERVICE_EDIT_RECIPE = "edit_recipe"
ATTR_CHANGES = "changes"

SERVICE_DELETE_RECIPE = "delete_recipe"

SERVICE_WRITE_RECIPE_TO_EASY_SLOT = "write_recipe_to_easy_slot"
ATTR_SLOT = "slot"

SERVICE_ADVANCED_SETTINGS = "advanced_settings"
ATTR_POUR_RADIUS_LEVEL = "pour_radius_level"
ATTR_VIBRATION_AMPLITUDE_LEVEL = "vibration_amplitude_level"
ATTR_DISPLAY_BRIGHTNESS_LEVEL = "display_brightness_level"

# Cloud boundary services (cloud_ prefix = the network is involved).
SERVICE_CLOUD_IMPORT_RECIPE = "cloud_import_recipe"
ATTR_SHARE_URL = "share_url"
ATTR_RECIPE_ID = "recipe_id"

SERVICE_CLOUD_EXPORT_RECIPE = "cloud_export_recipe"

# Public collective.xbloom.com community recipe hub search — a separate,
# unauthenticated API from the rest of the cloud_* services above (which all
# act on the user's own private cloud account). See _cloud_client.py's
# COLLECTIVE_API_BASE module comment.
SERVICE_CLOUD_SEARCH_COLLECTIVE_RECIPES = "cloud_search_collective_recipes"
ATTR_KEYWORD = "keyword"
ATTR_CATEGORY = "category"
ATTR_SRC = "src"
ATTR_MACHINE = "machine"
ATTR_CUP_TYPE = "cup_type"
ATTR_ORIGIN = "origin"
ATTR_VARIETAL = "varietal"
ATTR_PROCESS = "process"
ATTR_ROAST = "roast"
ATTR_FLAVOR = "flavor"
ATTR_SORT = "sort"
ATTR_SORT_DIRECTION = "sort_direction"

# LLM API identifiers
XBLOOM_LLM_API_ID = "xbloom_coffee"
XBLOOM_LLM_API_NAME = "XBloom Coffee Machine"

XBLOOM_LLM_PROMPT = (
    "You can control the XBloom Studio coffee machine. "
    "Use get_xbloom_status to check connection state, current temperature, "
    "weight, and brew state. "
    "LOCAL RECIPES are the source of truth — what the Recipe dropdown "
    "shows and what you brew from. Use list_xbloom_recipes to see them "
    "(optionally filtered by a name query). Use get_xbloom_recipe to read "
    "one recipe's full detail (grind, RPM, and each pour's volume / flow "
    "rate / pattern) before tweaking it. Every tool that takes a `recipe` "
    "argument accepts the recipe's local uid, cloud table id, share "
    "URL/id, or exact name — prefer the uid from list_xbloom_recipes when "
    "you have it. "
    "Use create_xbloom_recipe to build a new local recipe from scratch, "
    "edit_xbloom_recipe to change fields of an existing one (pass only "
    "the fields to change; a full pours list replaces the pours), and "
    "delete_xbloom_recipe to remove one locally (a cloud copy, if any, "
    "is untouched). Deleting is destructive — you MUST ask the user to "
    "confirm which recipe before passing confirmed=true. "
    "Use pour_xbloom to start a manual pour with a specific temperature (°C) "
    "and volume (ml). Use grind_xbloom to start a manual grind with a "
    "specific grind size and RPM — grind_xbloom and pour_xbloom are "
    "separate manual actions (grind does not pour, pour does not grind); "
    "use execute_xbloom_recipe instead to do both in one recipe-driven "
    "brew. Use tare_xbloom_scale to zero the scale. Use "
    "calibrate_xbloom_grinder to run the grinder's gear-position "
    "calibration sweep (~2 minutes, runs on its own) when the user reports "
    "grind sizes seem off or asks to (re)calibrate. "
    "Use execute_xbloom_recipe to run a saved recipe. To run it with "
    "adjustments for this brew only, pass grind_size and/or rpm (coffee "
    "recipes only), dose_g and/or ratio (pour volumes rescale so total "
    "water stays dose × ratio), cup_type, and/or pour_overrides (per-pour "
    "volume / flow_rate / pattern keyed by 0-based pour_index from "
    "get_xbloom_recipe). Overrides never change the stored recipe — use "
    "edit_xbloom_recipe for permanent changes. Only override what the "
    "user asked to change. "
    "Use write_xbloom_easy_slot to store a recipe on one of the machine's "
    "three onboard Easy Mode slots (A/B/C) so the user can run it from "
    "the device without Home Assistant — it does not brew anything. A "
    "share URL that isn't a local recipe yet is imported automatically "
    "first. "
    "All tools automatically connect over Bluetooth if the machine is not "
    "currently connected — you do not need a separate connect step. Only "
    "tell the user about the connection if a connect attempt fails. "
    "BEFORE calling execute_xbloom_recipe, you MUST ask the user to confirm "
    "(1) beans (or tea leaves for tea recipes) have been added, (2) the "
    "dripper is attached, and (3) for coffee only, the paper coffee filter "
    "is installed in the dripper (the machine cannot detect the filter on "
    "its own). Only set beans_confirmed=true, dripper_confirmed=true, and "
    "filter_confirmed=true after the user has explicitly confirmed each — "
    "see execute_xbloom_recipe's own description for the no-grind exception. "
    "The tool also verifies "
    "the cup is on the scale by reading its weight; if a cup was placed "
    "before the machine powered on the scale tares it to 0 g, in which "
    "case the tool will return cup_unverified — ask the user to confirm "
    "the cup is on, then call again with cup_confirmed=true. "
    "GRIND SIZE REFERENCE — recipe.grind_size uses the XBloom Studio scale "
    "(0=finest, 80=coarsest). Recommended ranges per brew method: "
    "Turkish 0–3, Espresso 0–18, Moka Pot 17–44, Filter Coffee Machine 12–66, "
    "Aeropress 13–71, Siphon 18–57, V60 21–47, Pour Over 22–68, "
    "Steep-and-release 25–59, Cupping 26–61, French Press 47–80, "
    "Cold Brew 58–80, Cold Drip 59–80. When the user asks what grind to use "
    "or wants advice on tuning a recipe, pick a value inside the matching "
    "range (start mid-range and adjust finer for slower extraction or "
    "coarser for faster). Tea recipes do not grind, so grind_size is ignored. "
    "CLOUD BOUNDARY: use import_xbloom_cloud_recipe to save a recipe from "
    "an XBloom share URL or id (e.g. from the official app's Share button, "
    "or a collective.xbloom.com/recipe link) as a local recipe — no XBloom "
    "account is needed. Use export_xbloom_recipe to push a local recipe to "
    "the user's XBloom cloud account (visible in the official app) and get "
    "a share link; re-exporting updates the same cloud recipe in place. "
    "Without a configured account nothing is uploaded and no link is "
    "returned — tell the user they can add one under Settings > Devices & "
    "Services > XBloom > Configure. Cloud recipes cannot be deleted from "
    "here — that's done in the official app. "
    "search_xbloom_collective_recipes browses XBloom's public community "
    "recipe hub (collective.xbloom.com) — no account needed. Use it when "
    "the user wants to discover new recipes shared by XBloom or other "
    "users (by keyword, coffee/tea category, origin, roast, flavor notes, "
    "etc.) rather than manage their own saved recipes. Results include a "
    "share_url — pass that to import_xbloom_cloud_recipe to save one "
    "locally."
)
