import json
import os

LOCALES_PATH = "/config/locales"
LANG = os.getenv("LANGUAGE", "en")

_cache = {}

def load_locale(lang: str):
    if lang in _cache:
        return _cache[lang]

    path = os.path.join(LOCALES_PATH, f"{lang}.json")

    if not os.path.isfile(path):
        if lang != "en":
            return load_locale("en")
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            _cache[lang] = data
            return data
    except:
        return {}

def t(key: str, **kwargs):
    data = load_locale(LANG)
    text = data.get(key)

    if not text:
        if LANG != "ru":
            text = load_locale("en").get(key, key)
        else:
            text = key

    try:
        return text.format(**kwargs)
    except:
        return text
