"""Service strings must not contain ICU placeholders, and no translated
string may contain angle brackets.

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

The first fix for that wrote the URL as `.../recipe/<id>`, and hassfest
rejected it: "the string should not contain HTML". Angle brackets are
banned in *every* translated string, not just service ones — hence the
second test. The placeholder is now a plain `ID`.
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


def test_no_translated_string_contains_angle_brackets():
    """hassfest rejects any translation string containing `<` or `>` as
    HTML, which fails CI for the whole integration."""
    offenders = []
    for file in _FILES:
        for path, text in _walk(json.loads(file.read_text())):
            if "<" in text or ">" in text:
                offenders.append(f"{file.name}: {path} -> {text}")
    assert not offenders, "\n".join(offenders)
