"""Chatbot translation layer (pure Python).

The conversational layer renders responses from canonical *English templates*
containing ``{placeholders}``. This layer translates the template for a target
language and then fills the placeholders — so localisation is stable even when
the parameter values are dates, amounts or names.

Fallback is the English template when a language has no entry.
"""
from __future__ import annotations

import json
import os
from typing import Optional

SUPPORTED_LANGUAGES = ("en", "hi", "fr")
_LANG_DIR = os.path.join(os.path.dirname(__file__), "languages")
_cache: dict = {}


def _load(lang: str) -> dict:
    if lang not in _cache:
        path = os.path.join(_LANG_DIR, f"{lang}.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                _cache[lang] = json.load(fh)
        else:
            _cache[lang] = {}
    return _cache[lang]


def list_languages() -> list:
    out = ["en"]
    for fn in sorted(os.listdir(_LANG_DIR)):
        if fn.endswith(".json"):
            out.append(fn[: -len(".json")])
    return out


def translate_template(template: str, to_lang: Optional[str] = None) -> str:
    """Translate a canonical English template (placeholders preserved)."""
    lang = (to_lang or "en").lower()
    if lang == "en" or not template:
        return template
    table = _load(lang)
    return table.get(template, template)


def render(template: str, params: dict = None, to_lang: Optional[str] = None, safe: bool = True) -> str:
    """Translate a template and substitute ``{placeholders}``."""
    localized = translate_template(template, to_lang)
    params = params or {}
    if safe:
        out = localized
        for key, value in params.items():
            out = out.replace("{" + str(key) + "}", str(value if value is not None else ""))
        return out
    return localized.format(**{k: str(v) for k, v in params.items()})