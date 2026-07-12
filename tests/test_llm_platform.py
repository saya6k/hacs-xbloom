"""The llm/ platform package: api_id gating, catalog, lazy-loading invariants.

Covers SPEC §4.2/§5-2 (tasks/2026-07-llm-platform-migration-spec.md):
- our tools never ride along in Assist or any foreign API (None gating),
- the catalog builds the full 13-tool set bound to one machine,
- the platform entry module stays import-light (AST) so a foreign API's
  tool collection never loads the tool implementations,
- the setup path never imports the llm/ package (AST, active from T3).

Gating/catalog/AST tests run on any HA version; only the success path of
``async_get_tools`` needs ``homeassistant.components.llm`` (HA ≥ 2026.8,
the devcontainer image) and skips elsewhere.
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.xbloom.const import (
    DATA_COORDINATOR,
    DOMAIN,
    XBLOOM_LLM_API_ID,
    XBLOOM_LLM_PROMPT,
)
from tests.test_llm_prompt import REGISTERED_TOOLS

COMPONENT_ROOT = (
    Path(__file__).resolve().parent.parent / "custom_components" / "xbloom"
)

# Modules that hold tool implementations (plus the catalog that aggregates
# them). None of these may be imported at module level by llm/__init__.py.
TOOL_MODULES = {
    "base",
    "catalog",
    "cloud_recipe",
    "local_recipe",
    "pour",
    "recipe",
    "slot",
    "status",
    "tare",
}


def _fake_hass(domain_data: dict) -> SimpleNamespace:
    return SimpleNamespace(data={DOMAIN: domain_data})


def _api_id(entry_id: str) -> str:
    return f"{XBLOOM_LLM_API_ID}_{entry_id}"


def _entry(coordinator: SimpleNamespace) -> dict:
    return {DATA_COORDINATOR: coordinator}


# --- api_id gating (None paths — no HA 2026.8 dependency) -----------------


def test_assist_api_gets_none():
    from custom_components.xbloom import llm as llm_platform

    hass = _fake_hass({"entry1": _entry(SimpleNamespace())})
    assert llm_platform.async_get_tools(hass, None, "assist") is None


def test_foreign_api_gets_none():
    from custom_components.xbloom import llm as llm_platform

    hass = _fake_hass({"entry1": _entry(SimpleNamespace())})
    assert llm_platform.async_get_tools(hass, None, "some_other_api") is None


def test_unknown_entry_gets_none():
    from custom_components.xbloom import llm as llm_platform

    hass = _fake_hass({"entry1": _entry(SimpleNamespace())})
    assert llm_platform.async_get_tools(hass, None, _api_id("nope")) is None


def test_no_domain_data_gets_none():
    from custom_components.xbloom import llm as llm_platform

    hass = SimpleNamespace(data={})
    assert llm_platform.async_get_tools(hass, None, _api_id("entry1")) is None


def test_non_entry_domain_key_gets_none():
    """hass.data[DOMAIN] holds non-entry keys (e.g. yaml_recipes) — never a match."""
    from custom_components.xbloom import llm as llm_platform

    hass = _fake_hass({"yaml_recipes": {"Recipe": {}}})
    assert llm_platform.async_get_tools(hass, None, _api_id("yaml_recipes")) is None


# --- catalog (builds on any HA version) ------------------------------------


def test_catalog_builds_the_full_tool_set():
    from custom_components.xbloom.llm.catalog import build_tools

    coordinator, hass = SimpleNamespace(), SimpleNamespace()
    tools = build_tools(coordinator, hass)
    assert len(tools) == len(REGISTERED_TOOLS)
    assert {tool.name for tool in tools} == set(REGISTERED_TOOLS)
    assert all(tool.coordinator is coordinator for tool in tools)
    assert all(tool.hass is hass for tool in tools)


def test_catalog_builds_fresh_instances_per_call():
    from custom_components.xbloom.llm.catalog import build_tools

    coord_a, coord_b = SimpleNamespace(), SimpleNamespace()
    hass = SimpleNamespace()
    tools_a = build_tools(coord_a, hass)
    tools_b = build_tools(coord_b, hass)
    assert all(tool.coordinator is coord_a for tool in tools_a)
    assert all(tool.coordinator is coord_b for tool in tools_b)
    assert not {id(t) for t in tools_a} & {id(t) for t in tools_b}


# --- success path (needs homeassistant.components.llm — HA ≥ 2026.8) ------


def test_own_api_returns_tools_and_prompt():
    pytest.importorskip(
        "homeassistant.components.llm", reason="HA ≥ 2026.8 (devcontainer image)"
    )
    from custom_components.xbloom import llm as llm_platform

    coordinator = SimpleNamespace()
    hass = _fake_hass({"entry1": _entry(coordinator)})
    result = llm_platform.async_get_tools(hass, None, _api_id("entry1"))
    assert result is not None
    assert {tool.name for tool in result.tools} == set(REGISTERED_TOOLS)
    assert result.prompt == XBLOOM_LLM_PROMPT
    assert all(tool.coordinator is coordinator for tool in result.tools)


def test_two_entries_each_bind_their_own_coordinator():
    pytest.importorskip(
        "homeassistant.components.llm", reason="HA ≥ 2026.8 (devcontainer image)"
    )
    from custom_components.xbloom import llm as llm_platform

    coord_a, coord_b = SimpleNamespace(), SimpleNamespace()
    hass = _fake_hass({"entry_a": _entry(coord_a), "entry_b": _entry(coord_b)})
    result_a = llm_platform.async_get_tools(hass, None, _api_id("entry_a"))
    result_b = llm_platform.async_get_tools(hass, None, _api_id("entry_b"))
    assert all(tool.coordinator is coord_a for tool in result_a.tools)
    assert all(tool.coordinator is coord_b for tool in result_b.tools)


# --- API shell (llm_api.py) delegates to the platform ----------------------


class _ShellHass(SimpleNamespace):
    """Minimal hass satisfying async_import_module + the API shell."""

    def __init__(self, domain_data: dict) -> None:
        super().__init__(data={DOMAIN: domain_data})

    @property
    def loop(self):
        return asyncio.get_running_loop()

    async def async_add_import_executor_job(self, func, *args):
        return func(*args)


def test_api_shell_keeps_id_and_name_format():
    from custom_components.xbloom.const import XBLOOM_LLM_API_NAME
    from custom_components.xbloom.llm_api import XBloomCoffeeAPI

    api = XBloomCoffeeAPI(_ShellHass({}), "entry1", "AA:BB:CC:DD:EE:FF")
    assert api.id == f"{XBLOOM_LLM_API_ID}_entry1"
    assert api.name == f"{XBLOOM_LLM_API_NAME} (AA:BB:CC:DD:EE:FF)"


def test_api_shell_builds_instance_via_platform():
    pytest.importorskip(
        "homeassistant.components.llm", reason="HA ≥ 2026.8 (devcontainer image)"
    )
    from custom_components.xbloom.llm_api import XBloomCoffeeAPI

    coordinator = SimpleNamespace()
    hass = _ShellHass({"entry1": _entry(coordinator)})
    api = XBloomCoffeeAPI(hass, "entry1", "AA:BB:CC:DD:EE:FF")
    instance = asyncio.run(api.async_get_api_instance(None))
    assert {tool.name for tool in instance.tools} == set(REGISTERED_TOOLS)
    assert instance.api_prompt == XBLOOM_LLM_PROMPT
    assert all(tool.coordinator is coordinator for tool in instance.tools)


def test_api_shell_raises_when_entry_is_gone():
    """Platform returns None (entry unloaded) → the shell must raise, not
    hand the agent an empty APIInstance."""
    from homeassistant.exceptions import HomeAssistantError

    from custom_components.xbloom.llm_api import XBloomCoffeeAPI

    hass = _ShellHass({})
    api = XBloomCoffeeAPI(hass, "gone", "AA:BB:CC:DD:EE:FF")
    with pytest.raises(HomeAssistantError):
        asyncio.run(api.async_get_api_instance(None))


# --- lazy-loading invariants (AST — SPEC §8) --------------------------------


def _module_level_imports(path: Path) -> tuple[set[str], set[str]]:
    """Return (relative modules, absolute modules) imported at module level.

    Only top-level statements count — imports inside functions (the lazy
    path) and under ``if TYPE_CHECKING:`` are intentionally allowed.
    """
    tree = ast.parse(path.read_text())
    relative: set[str] = set()
    absolute: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            if node.level >= 1:
                # ``from . import x`` has module=None — record the names.
                if node.module is None:
                    relative.update(alias.name for alias in node.names)
                else:
                    relative.add(node.module)
            else:
                absolute.add(node.module or "")
        elif isinstance(node, ast.Import):
            absolute.update(alias.name for alias in node.names)
    return relative, absolute


def test_platform_entry_module_stays_light():
    """llm/__init__.py must not pull tool/catalog modules (or components.llm)
    at module level — a foreign API's collection would load them otherwise."""
    relative, absolute = _module_level_imports(COMPONENT_ROOT / "llm" / "__init__.py")
    heavy = {mod for mod in relative if mod.split(".")[0] in TOOL_MODULES}
    assert not heavy, f"llm/__init__.py imports tool modules at module level: {heavy}"
    assert "homeassistant.components.llm" not in absolute, (
        "llm/__init__.py must import homeassistant.components.llm inside "
        "async_get_tools (success path only) so the module also loads on "
        "pre-2026.8 test hosts"
    )


def test_setup_path_never_imports_the_platform_package():
    """__init__.py / llm_api.py must not import .llm or any .llm.* submodule
    at module level — a submodule import executes llm/__init__.py (and the
    catalog pulls every tool), defeating lazy loading."""
    for fname in ("__init__.py", "llm_api.py"):
        relative, _ = _module_level_imports(COMPONENT_ROOT / fname)
        offending = {
            mod for mod in relative if mod == "llm" or mod.startswith("llm.")
        }
        assert not offending, f"{fname} imports the llm/ package: {offending}"
