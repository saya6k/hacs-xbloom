"""Constants for XBloom integration."""

DOMAIN = "xbloom"

# Config entry keys
CONF_MAC_ADDRESS = "mac_address"
CONF_TELEMETRY_INTERVAL = "telemetry_interval"
CONF_SESSION_TIMEOUT = "session_timeout"
CONF_RECIPES = "recipes"
CONF_WATER_SOURCE = "water_source"   # persisted in entry.options
CONF_MODE = "mode"                   # persisted in entry.options

# One-time recipe seed flags (entry.options). The local recipe store is the
# source of truth; the cloud is only consulted once per install (and once
# more when an account is added later) — see coordinator.async_seed_recipes.
CONF_RECIPES_SEEDED = "recipes_seeded"
CONF_ACCOUNT_RECIPES_SEEDED = "account_recipes_seeded"

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

# Data keys
DATA_COORDINATOR = "coordinator"
DATA_LLM_UNREGISTER = "llm_unregister"

# Services
SERVICE_EXECUTE_RECIPE = "execute_recipe"
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
    "Use list_xbloom_recipes to see configured recipes. "
    "Use get_xbloom_recipe to read one recipe's full detail (grind, RPM, and "
    "each pour's volume / flow rate / pattern) before tweaking it. "
    "Use pour_xbloom to start a manual pour with a specific temperature (°C) "
    "and volume (ml). "
    "Use execute_xbloom_recipe to run a saved recipe by name. To run it with "
    "adjustments for this brew only, pass grind_size and/or rpm (coffee "
    "recipes only), and/or pour_overrides (per-pour volume / flow_rate / "
    "pattern keyed by 0-based pour_index from get_xbloom_recipe). Only "
    "override what the user asked to change. "
    "All tools automatically connect over Bluetooth if the machine is not "
    "currently connected — you do not need a separate connect step. Only "
    "tell the user about the connection if a connect attempt fails. "
    "BEFORE calling execute_xbloom_recipe, you MUST ask the user to confirm "
    "(1) beans (or tea leaves for tea recipes) have been added, and (2) the "
    "paper coffee filter is installed (the machine cannot detect the filter "
    "on its own). Only set beans_confirmed=true and filter_confirmed=true "
    "after the user has explicitly confirmed each. The tool also verifies "
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
    "Use import_xbloom_cloud_recipe to import a recipe from an XBloom cloud "
    "share URL or id (e.g. from the official app's Share button) — no "
    "XBloom account is needed for this. It saves the recipe locally so it "
    "then shows up in list_xbloom_recipes / execute_xbloom_recipe. "
    "CLOUD vs LOCAL recipes: local tools (list/get/execute_xbloom_recipe) "
    "manage recipes stored on this machine and are what you use to brew. "
    "The cloud tools (search/create/export/edit/delete_xbloom_cloud_recipe) "
    "manage recipes on the user's XBloom cloud account, visible in the "
    "official app — use them only when the user explicitly wants to "
    "browse, save, share, or clean up their cloud account, not for "
    "brewing. All cloud tools except import require an XBloom account to "
    "be configured for the machine; if one isn't, they return a "
    "cloud_not_configured error — tell the user to add an account under "
    "Settings > Devices & Services > XBloom > Configure. "
    "delete_xbloom_cloud_recipe is destructive and permanent — like "
    "execute_xbloom_recipe's beans/filter checks, you MUST ask the user "
    "to explicitly confirm which recipe before passing confirmed=true. "
    "search_xbloom_collective_recipes is a THIRD, separate recipe source: "
    "XBloom's public community recipe hub (collective.xbloom.com), browsable "
    "by anyone with no XBloom account. Use it when the user wants to "
    "discover new recipes shared by XBloom or other users (by keyword, "
    "coffee/tea category, origin, roast, flavor notes, etc.) rather than "
    "manage their own saved recipes. Results include a share_url — pass "
    "that straight to import_xbloom_cloud_recipe to save one locally."
)
