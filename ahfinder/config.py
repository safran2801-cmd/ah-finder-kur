"""Konfiguration.

API-Keys werden aus st.secrets (Streamlit Cloud) gelesen,
mit Fallback auf Umgebungsvariablen. Kein Key im Code.
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR: Path = Path(__file__).resolve().parent.parent
CACHE_DIR: Path = BASE_DIR / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _secret(key: str, env_var: str, default: str = "") -> str:
    """Liest erst aus st.secrets (Streamlit Cloud), dann Umgebungsvariable."""
    try:
        import streamlit as st
        val = st.secrets.get(key)
        if val:
            return str(val)
    except Exception:
        pass
    return os.environ.get(env_var, default)


INFOMANIAK_API_KEY: str = _secret("INFOMANIAK_API_KEY", "INFOMANIAK_API_KEY")
API_ENDPOINT: str = _secret(
    "INFOMANIAK_API_ENDPOINT",
    "INFOMANIAK_API_ENDPOINT",
    "https://api.infomaniak.com/2/ai/108404/openai/v1/chat/completions",
)
MODEL_NAME: str = _secret(
    "INFOMANIAK_MODEL",
    "INFOMANIAK_MODEL",
    "mistralai/Mistral-Small-4-119B-2603",
)

CONFIG: dict = {
    "overpass": {
        "endpoint": "https://overpass.osm.ch/api/interpreter",
        "fallback": "https://overpass-api.de/api/interpreter",
        "fallbacks": [
            "https://overpass-api.de/api/interpreter",
            "https://z.overpass-api.de/api/interpreter",
        ],
        "timeout": 12,
    },
    "open_meteo": {
        "endpoint": "https://api.open-meteo.com/v1/forecast",
        "timeout": 15,
    },
    "wikipedia": {
        "de_endpoint": "https://de.wikipedia.org/api/rest_v1",
        "en_endpoint": "https://en.wikipedia.org/api/rest_v1",
        "timeout": 10,
    },
    "wikidata": {
        "endpoint": "https://www.wikidata.org/w/api.php",
        "timeout": 10,
    },
    "duckduckgo": {
        "endpoint": "https://html.duckduckgo.com/html/",
        "timeout": 10,
    },
    "cache": {
        "dir": CACHE_DIR,
        "huetten_ttl": 86400,
        "wetter_ttl": 21600,
        "ki_ttl": 21600,
    },
    "overpass_bbox": {
        "south": 46.3,
        "west": 9.5,
        "north": 47.8,
        "east": 13.5,
    },
    "max_huetten_weather": 300,
    "enrich_n": 15,
    "photo_enrich_n_max": 300,
    "photo_enrich_batch_size": 10,
    "top_n": 9,
}


def cache_key(*parts) -> str:
    return "::".join(str(p) for p in parts)
