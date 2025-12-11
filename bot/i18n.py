# bot/i18n.py
import os
import json
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

DEFAULT_LANG = os.getenv("LANGUAGE", "en").lower()
LOCALES_PATHS = [
    Path("/config/locales"),
    Path("/app/locales"),
    Path(__file__).parent.parent / "locales",
]

_loaded_locales = {}


def _load_locale(lang: str):
    if lang in _loaded_locales:
        return _loaded_locales[lang]

    for base in LOCALES_PATHS:
        path = base / f"{lang}.json"
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    _loaded_locales[lang] = data
                    logger.info(f"Locale '{lang}' loaded from {path}")
                    return data
            except Exception as e:
                logger.error(f"Failed to load locale {path}: {e}")

    if lang != "en":
        logger.warning(f"Locale '{lang}' not found – falling back to 'en'")
        return _load_locale("en")

    _loaded_locales["en"] = {}
    return {}


def t(key: str, **kwargs):
    lang = os.getenv("LANGUAGE", DEFAULT_LANG).lower()
    locale = _load_locale(lang)
    text = locale.get(key)
    if text is None and lang != "en":
        text = _load_locale("en").get(key)
    if text is None:
        text = key
    try:
        return text.format(**kwargs) if kwargs else text
    except Exception:
        return text
