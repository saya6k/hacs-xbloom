"""Service strings must not contain ICU placeholders.

Hardware-reported 2026-08-24: opening the services UI spammed

    ERROR [frontend.js…] Failed to format translation for key
    'component.xbloom.services.cloud_import_recipe.fields.share_url.description'
    in language 'ko'. [formatjs Error: MISSING_VALUE] The intl string context
    variable "id" was not provided …

The description documented a community-hub URL as
`collective.xbloom.com/recipe/{id}`, and the frontend runs every translated
string through formatjs — so `{id}` was read as a placeholder, not as
literal text. Config-flow strings can legitimately use placeholders (the
flow supplies description_placeholders), but service names/descriptions
have no such mechanism, so any brace there is a bug.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "xbloom"
_FILES = [
    _COMPONENT / "strings.json",
    *sorted((_COMPONENT / "translations").glob("*.json")),
]
_PLACEHOLDER = re.compile(r"\{[^}]*\}")


def _walk(node, path=""):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _walk(value, f"{path}.{key}" if path else key)
    elif isinstance(node, str):
        yield path, node


def test_service_strings_have_no_icu_placeholders():
    offenders = []
    for file in _FILES:
        services = json.loads(file.read_text()).get("services", {})
        for path, text in _walk(services):
            if _PLACEHOLDER.search(text):
                offenders.append(f"{file.name}: services.{path} -> {text}")
    assert not offenders, "\n".join(offenders)
