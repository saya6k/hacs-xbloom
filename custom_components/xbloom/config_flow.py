"""Config flow for XBloom integration."""
from __future__ import annotations

import re
import logging
from typing import Any

import voluptuous as vol
import yaml

from homeassistant import config_entries
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_EMAIL,
    CONF_MAC_ADDRESS,
    CONF_PASSWORD,
    CONF_RECIPES,
    CONF_TELEMETRY_INTERVAL,
    CONF_SESSION_TIMEOUT,
    CONF_TEMP_UNIT,
    CONF_WATER_SOURCE,
    CONF_WEIGHT_UNIT,
    DATA_COORDINATOR,
    DEFAULT_TELEMETRY_INTERVAL,
    DEFAULT_SESSION_TIMEOUT,
    DEFAULT_TEMP_UNIT,
    DEFAULT_WATER_SOURCE,
    DEFAULT_WEIGHT_UNIT,
    DOMAIN,
)
from .coordinator import WATER_SOURCE_OPTIONS
from .schema import (
    RECIPE_PROTECTED_FIELDS,
    RECIPE_SCHEMA,
    new_recipe_uid,
    strip_protected_recipe_fields,
)

_LOGGER = logging.getLogger(__name__)

MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")


def _valid_mac(mac: str) -> bool:
    return bool(MAC_RE.match(mac.strip()))


STEP_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_MAC_ADDRESS): str,
        vol.Optional(CONF_TELEMETRY_INTERVAL, default=DEFAULT_TELEMETRY_INTERVAL): vol.All(
            int, vol.Range(min=1, max=60)
        ),
        vol.Optional(CONF_SESSION_TIMEOUT, default=DEFAULT_SESSION_TIMEOUT): vol.All(
            int, vol.Range(min=10, max=3600)
        ),
    }
)


class XBloomConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for XBloom."""

    # Bumped 1 -> 2: recipe schema field rename (bean_weight/total_water ->
    # dose_g/ratio, pour volume/temperature/pausing -> volume_ml/
    # temperature_c/pause_seconds). Bumped 2 -> 3: stored recipes gained
    # local-store metadata (uid/source). See __init__.async_migrate_entry.
    VERSION = 3

    def __init__(self) -> None:
        self._discovered_devices: list[dict] = []
        self._mac_step_data: dict[str, Any] = {}
        self._discovered_mac: str | None = None
        self._discovered_name: str | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle a machine discovered via the service_uuid matcher in manifest.json."""
        mac = discovery_info.address.upper()
        await self.async_set_unique_id(mac)
        self._abort_if_unique_id_configured()

        self._discovered_mac = mac
        self._discovered_name = discovery_info.name or mac
        self.context["title_placeholders"] = {"name": self._discovered_name}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """One-click confirmation for a Bluetooth-discovered machine."""
        errors: dict[str, str] = {}
        mac = self._discovered_mac
        assert mac is not None

        if user_input is not None:
            try:
                from ._client import HABleakConnection, XBloomClientWithEvents

                client = XBloomClientWithEvents(
                    mac_address=mac, connection=HABleakConnection(self.hass)
                )
                ok = await client.connect(timeout=15.0)
                if ok:
                    await client.disconnect()
                else:
                    errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "cannot_connect"

            if not errors:
                self._mac_step_data = {
                    CONF_MAC_ADDRESS: mac,
                    CONF_TELEMETRY_INTERVAL: DEFAULT_TELEMETRY_INTERVAL,
                    CONF_SESSION_TIMEOUT: DEFAULT_SESSION_TIMEOUT,
                }
                return await self.async_step_account()

        return self.async_show_form(
            step_id="bluetooth_confirm",
            data_schema=vol.Schema({}),
            description_placeholders={"name": self._discovered_name or mac},
            errors=errors,
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            mac = user_input[CONF_MAC_ADDRESS].strip().upper()

            if not _valid_mac(mac):
                errors[CONF_MAC_ADDRESS] = "invalid_mac"
            else:
                # Check uniqueness
                await self.async_set_unique_id(mac)
                self._abort_if_unique_id_configured()

                # Quick connection test
                try:
                    from ._client import HABleakConnection, XBloomClientWithEvents

                    client = XBloomClientWithEvents(
                        mac_address=mac, connection=HABleakConnection(self.hass)
                    )
                    ok = await client.connect(timeout=15.0)
                    if ok:
                        await client.disconnect()
                    else:
                        errors["base"] = "cannot_connect"
                except Exception:
                    errors["base"] = "cannot_connect"

                if not errors:
                    self._mac_step_data = {
                        CONF_MAC_ADDRESS: mac,
                        CONF_TELEMETRY_INTERVAL: user_input.get(
                            CONF_TELEMETRY_INTERVAL, DEFAULT_TELEMETRY_INTERVAL
                        ),
                        CONF_SESSION_TIMEOUT: user_input.get(
                            CONF_SESSION_TIMEOUT, DEFAULT_SESSION_TIMEOUT
                        ),
                    }
                    return await self.async_step_account()

        # Show form — optionally pre-fill with discovered device
        discovered_mac = ""
        try:
            from xbloom.scanner import discover_devices

            _LOGGER.debug("Scanning for XBloom devices…")
            devices = await discover_devices(timeout=5.0)
            if devices:
                discovered_mac = devices[0].address
                _LOGGER.info("Auto-discovered XBloom: %s", discovered_mac)
        except Exception as exc:
            _LOGGER.debug("BLE scan error (non-fatal): %s", exc)

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_MAC_ADDRESS,
                    default=discovered_mac or vol.UNDEFINED,
                ): str,
                vol.Optional(
                    CONF_TELEMETRY_INTERVAL,
                    default=DEFAULT_TELEMETRY_INTERVAL,
                ): vol.All(int, vol.Range(min=1, max=60)),
                vol.Optional(
                    CONF_SESSION_TIMEOUT,
                    default=DEFAULT_SESSION_TIMEOUT,
                ): vol.All(int, vol.Range(min=10, max=3600)),
            }
        )

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_account(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Optional XBloom cloud account (recipe sync) — entirely skippable.

        Leaving both fields blank skips cloud setup; the integration works
        exactly as it does without an account (BLE-only). No connectivity
        test is done here — a bad login is only discovered lazily, the
        first time a cloud-backed service/tool is actually used, so this
        step stays fast and doesn't fail setup if the cloud is briefly down.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            email = (user_input.get(CONF_EMAIL) or "").strip()
            password = user_input.get(CONF_PASSWORD) or ""

            if bool(email) != bool(password):
                errors["base"] = "account_incomplete"
            else:
                data = dict(self._mac_step_data)
                if email and password:
                    data[CONF_EMAIL] = email
                    data[CONF_PASSWORD] = password
                return self.async_create_entry(
                    title=f"XBloom ({self._mac_step_data[CONF_MAC_ADDRESS]})",
                    data=data,
                )

        return self.async_show_form(
            step_id="account",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_EMAIL): str,
                    vol.Optional(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> XBloomOptionsFlow:
        return XBloomOptionsFlow(config_entry)


_RECIPE_YAML_PLACEHOLDER = """\
name: My Recipe
grind_size: 60
rpm: 80
dose_g: 16.0
ratio: 15.625
cup_type: omni_dripper
pours:
  - volume_ml: 50
    temperature_c: 92
    pause_seconds: 45
    pattern: spiral
    vibration: after
  - volume_ml: 100
    temperature_c: 92
    pause_seconds: 30
    pattern: spiral
  - volume_ml: 100
    temperature_c: 92
    pattern: spiral
"""


def _options_recipes(entry: config_entries.ConfigEntry) -> dict[str, dict]:
    """Return UI-managed recipes from entry.options (valid recipes only, no tombstones)."""
    raw = entry.options.get(CONF_RECIPES) or {}
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if v is not None}


def _all_visible_recipes(entry: config_entries.ConfigEntry, hass) -> dict[str, dict]:
    """Merge YAML + options recipes, respecting tombstones.

    A ``None`` value in options is a tombstone that hides a same-named
    recipe from the YAML layer. Mirrors ``coordinator._rebuild_recipes``
    — if the merge logic changes in one place, check the other.
    """
    merged: dict[str, dict] = {}
    merged.update(hass.data.get(DOMAIN, {}).get("yaml_recipes", {}))
    options_raw = entry.options.get(CONF_RECIPES) or {}
    if isinstance(options_raw, dict):
        for name, recipe in options_raw.items():
            if recipe is None:
                merged.pop(name, None)  # tombstone
            else:
                merged[name] = recipe
    return merged


def _save_options(
    entry: config_entries.ConfigEntry,
    *,
    recipes: dict[str, dict] | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge the existing options with new recipes / settings and return the blob."""
    new_options: dict[str, Any] = dict(entry.options)
    if recipes is not None:
        new_options[CONF_RECIPES] = recipes
    if settings:
        new_options.update(settings)
    return new_options


class XBloomOptionsFlow(config_entries.OptionsFlow):
    """Options flow — menu-driven settings + recipe CRUD."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry
        self._editing: str | None = None

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=["settings", "account", "add_recipe", "edit_recipe", "delete_recipe"],
        )

    # ── Cloud account (add / update / clear) ─────────────────────────

    async def async_step_account(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Add, update, or clear the XBloom cloud account after initial setup.

        Mirrors the optional account step from the initial ConfigFlow, but
        lives here so users who skipped it there can add credentials later
        (or change/clear them) without deleting and re-adding the
        integration. Persists to ``entry.data`` directly (not
        ``entry.options``, which this flow's own async_create_entry always
        writes to) — the existing options-update-listener reload picks up
        the change on the next coordinator setup either way.
        """
        errors: dict[str, str] = {}
        stored_email = self._entry.data.get(CONF_EMAIL, "")
        has_existing = bool(stored_email and self._entry.data.get(CONF_PASSWORD))

        if user_input is not None:
            email = (user_input.get(CONF_EMAIL) or "").strip()
            password = user_input.get(CONF_PASSWORD) or ""

            new_data: dict[str, Any] | None = None
            if not email and not password:
                if has_existing:
                    new_data = {
                        k: v
                        for k, v in self._entry.data.items()
                        if k not in (CONF_EMAIL, CONF_PASSWORD)
                    }
                # else: nothing stored, nothing entered — no-op.
            elif email and password:
                new_data = {**self._entry.data, CONF_EMAIL: email, CONF_PASSWORD: password}
            elif email and not password:
                if not (email == stored_email and has_existing):
                    errors["base"] = "account_password_required"
                # else: unchanged resubmit — no-op.
            else:  # password and not email
                errors["base"] = "account_email_required"

            if not errors:
                if new_data is not None:
                    self.hass.config_entries.async_update_entry(self._entry, data=new_data)
                return self.async_create_entry(title="", data=dict(self._entry.options))

        return self.async_show_form(
            step_id="account",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_EMAIL, default=stored_email): str,
                    vol.Optional(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
        )

    # ── Settings (telemetry + session timeout + display units + water source) ──

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            settings = dict(user_input)
            water_source_name = settings.pop(CONF_WATER_SOURCE, "tank")
            settings[CONF_WATER_SOURCE] = WATER_SOURCE_OPTIONS.get(
                water_source_name, DEFAULT_WATER_SOURCE
            )
            return self.async_create_entry(
                title="",
                data=_save_options(self._entry, settings=settings),
            )

        current_water_source = self._entry.options.get(
            CONF_WATER_SOURCE, DEFAULT_WATER_SOURCE
        )
        water_source_name = next(
            (
                name
                for name, value in WATER_SOURCE_OPTIONS.items()
                if value == current_water_source
            ),
            "tank",
        )

        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_TELEMETRY_INTERVAL,
                        default=self._entry.options.get(
                            CONF_TELEMETRY_INTERVAL,
                            self._entry.data.get(
                                CONF_TELEMETRY_INTERVAL, DEFAULT_TELEMETRY_INTERVAL
                            ),
                        ),
                    ): vol.All(int, vol.Range(min=1, max=60)),
                    vol.Optional(
                        CONF_SESSION_TIMEOUT,
                        default=self._entry.options.get(
                            CONF_SESSION_TIMEOUT,
                            self._entry.data.get(
                                CONF_SESSION_TIMEOUT, DEFAULT_SESSION_TIMEOUT
                            ),
                        ),
                    ): vol.All(int, vol.Range(min=10, max=3600)),
                    vol.Optional(
                        CONF_WEIGHT_UNIT,
                        default=self._entry.options.get(
                            CONF_WEIGHT_UNIT, DEFAULT_WEIGHT_UNIT
                        ),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=["g", "oz", "ml"],
                            mode=SelectSelectorMode.DROPDOWN,
                            translation_key="weight_unit",
                        )
                    ),
                    vol.Optional(
                        CONF_TEMP_UNIT,
                        default=self._entry.options.get(
                            CONF_TEMP_UNIT, DEFAULT_TEMP_UNIT
                        ),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=["c", "f"],
                            mode=SelectSelectorMode.DROPDOWN,
                            translation_key="temp_unit",
                        )
                    ),
                    vol.Optional(
                        CONF_WATER_SOURCE, default=water_source_name
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=list(WATER_SOURCE_OPTIONS.keys()),
                            mode=SelectSelectorMode.DROPDOWN,
                            translation_key="water_source",
                        )
                    ),
                }
            ),
        )

    # ── Add recipe ───────────────────────────────────────────────────

    async def async_step_add_recipe(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors, placeholders = {}, {}
        default_yaml = _RECIPE_YAML_PLACEHOLDER

        if user_input is not None:
            default_yaml = user_input.get("recipe_yaml", default_yaml)
            recipe, err = _parse_and_validate(default_yaml)
            if err:
                errors["base"], placeholders["error"] = err
            else:
                existing = _all_visible_recipes(self._entry, self.hass)
                if recipe["name"] in existing:
                    errors["base"] = "recipe_exists"
                    placeholders["error"] = recipe["name"]
                else:
                    recipe["uid"] = new_recipe_uid()
                    recipe["source"] = "manual"
                    existing_opts = _options_recipes(self._entry)
                    existing_opts[recipe["name"]] = recipe
                    return self.async_create_entry(
                        title="",
                        data=_save_options(self._entry, recipes=existing_opts),
                    )

        return self.async_show_form(
            step_id="add_recipe",
            data_schema=vol.Schema(
                {
                    vol.Required("recipe_yaml", default=default_yaml): TextSelector(
                        TextSelectorConfig(multiline=True, type=TextSelectorType.TEXT)
                    ),
                }
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    # ── Edit recipe (2 steps: pick → YAML) ───────────────────────────

    async def async_step_edit_recipe(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        existing = _all_visible_recipes(self._entry, self.hass)
        if not existing:
            return self.async_abort(reason="no_recipes")

        if user_input is None:
            return self.async_show_form(
                step_id="edit_recipe",
                data_schema=vol.Schema(
                    {
                        vol.Required("recipe_name"): SelectSelector(
                            SelectSelectorConfig(
                                options=sorted(existing.keys()),
                                mode=SelectSelectorMode.DROPDOWN,
                            )
                        ),
                    }
                ),
            )

        self._editing = user_input["recipe_name"]
        return await self.async_step_edit_recipe_yaml()

    async def async_step_edit_recipe_yaml(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        visible = _all_visible_recipes(self._entry, self.hass)
        if not self._editing or self._editing not in visible:
            return self.async_abort(reason="no_recipes")

        errors, placeholders = {}, {}
        default_yaml = yaml.safe_dump(
            dict(visible[self._editing]), allow_unicode=True, sort_keys=False
        )

        if user_input is not None:
            default_yaml = user_input.get("recipe_yaml", default_yaml)
            recipe, err = _parse_and_validate(default_yaml)
            if err:
                errors["base"], placeholders["error"] = err
            else:
                # _parse_and_validate strips uid/cloud_table_id/share_url/
                # source (blocking a pasted-YAML spoof) — restore the
                # original recipe's own values for those, same as
                # coordinator.async_edit_local_recipe. The textarea shows
                # them pre-filled, but a user leaving them untouched (or
                # editing other fields) must not lose the real identity.
                original = visible[self._editing]
                for key in RECIPE_PROTECTED_FIELDS:
                    if key in original:
                        recipe[key] = original[key]
                # Allow rename — drop the old key from options, add under the
                # new name.  If the original recipe lives in a lower layer
                # (defaults / YAML) it wasn't in options to begin with, so the
                # filter is a no-op for it; the new version is saved to options
                # and shadows the lower layer by name.
                existing = _options_recipes(self._entry)
                new_recipes = {
                    k: v for k, v in existing.items() if k != self._editing
                }
                new_recipes[recipe["name"]] = recipe
                return self.async_create_entry(
                    title="",
                    data=_save_options(self._entry, recipes=new_recipes),
                )

        return self.async_show_form(
            step_id="edit_recipe_yaml",
            data_schema=vol.Schema(
                {
                    vol.Required("recipe_yaml", default=default_yaml): TextSelector(
                        TextSelectorConfig(multiline=True, type=TextSelectorType.TEXT)
                    ),
                }
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    # ── Delete recipe ────────────────────────────────────────────────

    async def async_step_delete_recipe(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        visible = _all_visible_recipes(self._entry, self.hass)
        if not visible:
            return self.async_abort(reason="no_recipes")

        if user_input is None:
            return self.async_show_form(
                step_id="delete_recipe",
                data_schema=vol.Schema(
                    {
                        vol.Required("recipe_name"): SelectSelector(
                            SelectSelectorConfig(
                                options=sorted(visible.keys()),
                                mode=SelectSelectorMode.DROPDOWN,
                            )
                        ),
                    }
                ),
            )

        name = user_input["recipe_name"]
        existing = _options_recipes(self._entry)
        if name in existing:
            # Options-owned recipe — remove it entirely.
            del existing[name]
        else:
            # Default or YAML recipe — add a tombstone so it stays hidden.
            existing[name] = None
        return self.async_create_entry(
            title="",
            data=_save_options(self._entry, recipes=existing),
        )


def _parse_and_validate(raw: str) -> tuple[dict | None, tuple[str, str] | None]:
    """Parse YAML + RECIPE_SCHEMA. Returns (recipe, None) on success or
    (None, (error_key, detail)) on failure.

    Strips uid/cloud_table_id/share_url/source before validating — same
    as coordinator.create_local_recipe/async_edit_local_recipe — so
    pasted YAML here can't spoof another recipe's identity or claim a
    cloud_table_id it doesn't own either. Callers assign/preserve those
    fields themselves afterward.
    """
    try:
        parsed = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        return None, ("invalid_yaml", str(exc))
    if not isinstance(parsed, dict):
        return None, ("invalid_yaml", "recipe must be a YAML mapping")
    try:
        return RECIPE_SCHEMA(strip_protected_recipe_fields(parsed)), None
    except vol.Invalid as exc:
        return None, ("invalid_recipe", str(exc))
