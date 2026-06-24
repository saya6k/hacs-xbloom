"""Constants for XBloom integration."""

DOMAIN = "xbloom"

# Config entry keys
CONF_MAC_ADDRESS = "mac_address"
CONF_TELEMETRY_INTERVAL = "telemetry_interval"
CONF_SESSION_TIMEOUT = "session_timeout"
CONF_RECIPES = "recipes"
CONF_WATER_SOURCE = "water_source"   # persisted in entry.options
CONF_MODE = "mode"                   # persisted in entry.options

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
ATTR_RECIPE_NAME = "recipe_name"
ATTR_GRIND_SIZE = "grind_size"
ATTR_RPM = "rpm"
ATTR_BYPASS_VOLUME = "bypass_volume"
ATTR_BYPASS_TEMPERATURE = "bypass_temperature"

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
    "coarser for faster). Tea recipes do not grind, so grind_size is ignored."
)
