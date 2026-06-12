"""Open-Meteo Wetter + Bewertung."""
from __future__ import annotations

import json
from typing import List, Optional

from .cache import cache_get, cache_set
from .config import CONFIG, cache_key
from .http import http_multi_get


WEATHER_INFO = {
    0:  ("Klar",              "\u2600\ufe0f"),
    1:  ("Meist klar",        "\U0001f324\ufe0f"),
    2:  ("Teils bew\u00f6lkt",     "\u26c5"),
    3:  ("Bew\u00f6lkt",           "\u2601\ufe0f"),
    45: ("Nebel",             "\U0001f32b\ufe0f"),
    48: ("Nebel",             "\U0001f32b\ufe0f"),
    51: ("Leichter Niesel",   "\U0001f327\ufe0f"),
    53: ("Nieselregen",       "\U0001f327\ufe0f"),
    55: ("Starker Niesel",    "\U0001f327\ufe0f"),
    61: ("Leichter Regen",    "\U0001f327\ufe0f"),
    63: ("Regen",             "\U0001f327\ufe0f"),
    65: ("Starker Regen",     "\u26c8\ufe0f"),
    71: ("Leichter Schnee",   "\U0001f328\ufe0f"),
    73: ("Schneefall",        "\U0001f328\ufe0f"),
    75: ("Starker Schnee",    "\u2744\ufe0f"),
    80: ("Regenschauer",      "\U0001f326\ufe0f"),
    81: ("Regenschauer",      "\U0001f326\ufe0f"),
    82: ("Starkregen",        "\u26c8\ufe0f"),
    85: ("Schneeschauer",     "\U0001f328\ufe0f"),
    86: ("Schneeschauer",     "\U0001f328\ufe0f"),
    95: ("Gewitter",          "\u26c8\ufe0f"),
    96: ("Gewitter/Hagel",    "\u26c8\ufe0f"),
    99: ("Schweres Gewitter", "\u26c8\ufe0f"),
}


def weather_info(code: int) -> tuple:
    return WEATHER_INFO.get(int(code), ("Unbekannt", "\u2753"))


def _score_day(d: dict) -> float:
    wc   = int(d.get("weathercode") or 0)
    sun  = float(d.get("sunshine_duration") or 0) / 3600  # Sekunden → Stunden
    prec = float(d.get("precipitation_sum") or 0)
    tmax = float(d.get("temperature_2m_max") or 10)

    # Basiswert aus Wettercode (primäre Quelle, kein Addieren mit Niederschlag)
    if   wc == 0:          base = 100
    elif wc == 1:          base = 90
    elif wc == 2:          base = 75
    elif wc == 3:          base = 55
    elif wc < 55:          base = 40   # Nieselregen
    elif wc < 65:          base = 20   # leichter bis mässiger Regen
    elif wc < 75:          base = 10   # Schneefall
    elif wc < 82:          base = 5    # Schauer
    else:                  base = 0    # Gewitter – hartes Veto

    # Sonnenschein als Multiplikator (0.7 bei 0h → 1.2 bei ≥10h)
    sun_factor = 0.7 + min(sun / 10, 1.0) * 0.5

    # Niederschlag kollabiert den Score (15 mm = Factor 0.0)
    rain_factor = max(0.1, 1.0 - prec / 15)

    # Temperaturkomfort: optimal 5–20°C für alpine Touren
    if 5 <= tmax <= 20:    temp_factor = 1.0
    elif tmax < -5 or tmax > 30: temp_factor = 0.8
    else:                  temp_factor = 0.9

    return base * sun_factor * rain_factor * temp_factor


def _format_day(d: dict) -> dict:
    info = weather_info(int(d.get("weathercode") or 0))
    return {
        "weathercode": int(d.get("weathercode") or 0),
        "weatherText": info[0],
        "weatherIcon": info[1],
        "sunshineHours": round(float(d.get("sunshine_duration") or 0) / 3600, 1),
        "precipitation": float(d.get("precipitation_sum") or 0),
        "snowfall": float(d.get("snowfall_sum") or 0),
        "radiation": round(float(d.get("shortwave_radiation_sum") or 0), 1),
        "tempMax": round(float(d.get("temperature_2m_max") or 0), 1),
        "tempMin": round(float(d.get("temperature_2m_min") or 0), 1),
    }


def score_weather(daily: dict, sat: str, sun: str) -> Optional[dict]:
    times = daily.get("time") or []
    if not times:
        return None
    try:
        i_sat = times.index(sat)
        i_sun = times.index(sun)
    except ValueError:
        return None

    def pick(i: int) -> dict:
        return {
            "weathercode": (daily.get("weathercode") or [None] * (i + 1))[i],
            "sunshine_duration": (daily.get("sunshine_duration") or [0] * (i + 1))[i],
            "precipitation_sum": (daily.get("precipitation_sum") or [0] * (i + 1))[i],
            "snowfall_sum": (daily.get("snowfall_sum") or [0] * (i + 1))[i],
            "shortwave_radiation_sum": (daily.get("shortwave_radiation_sum") or [0] * (i + 1))[i],
            "temperature_2m_max": (daily.get("temperature_2m_max") or [0] * (i + 1))[i],
            "temperature_2m_min": (daily.get("temperature_2m_min") or [0] * (i + 1))[i],
        }

    d_sat = pick(i_sat)
    d_sun = pick(i_sun)
    total = _score_day(d_sat) + _score_day(d_sun)

    return {
        "total": int(round(total)),
        "sat": _format_day(d_sat),
        "sun": _format_day(d_sun),
    }


def fetch_weather_for_huts(huts: List[dict], sat: str, sun: str) -> list:
    """Holt Wetterdaten via Batch-Request (alle Hütten in einem API-Call).

    Open-Meteo unterstützt mehrere Koordinaten in einer Anfrage (kommagetrennt).
    Das ist freundlicher gegenüber der API als viele Einzelanfragen.
    """
    from .http import http_get

    results: list = [None] * len(huts)
    uncached: list = []  # (original_index, hut)

    for i, h in enumerate(huts):
        ck = cache_key("wetter", h["lat"], h["lon"], sat, sun)
        cached = cache_get(ck)
        if cached is not None:
            results[i] = cached
        else:
            uncached.append((i, h))

    if not uncached:
        return results

    lats = ",".join(str(h["lat"]) for _, h in uncached)
    lons = ",".join(str(h["lon"]) for _, h in uncached)
    url = (
        f"{CONFIG['open_meteo']['endpoint']}"
        f"?latitude={lats}&longitude={lons}"
        f"&daily=weathercode,sunshine_duration,precipitation_sum,snowfall_sum,"
        f"shortwave_radiation_sum,temperature_2m_max,temperature_2m_min"
        f"&timezone=Europe%2FBerlin&start_date={sat}&end_date={sun}"
    )

    r = http_get(url, CONFIG["open_meteo"]["timeout"])
    if r["code"] != 200 or not r["body"]:
        return results

    try:
        j = json.loads(r["body"])
    except json.JSONDecodeError:
        return results

    # Einzelne Hütte → dict; mehrere → list
    if isinstance(j, dict):
        j = [j]
    if not isinstance(j, list):
        return results

    for list_idx, (hut_idx, h) in enumerate(uncached):
        if list_idx >= len(j):
            break
        item = j[list_idx]
        daily = None
        if isinstance(item, dict) and "daily" in item and "time" in (item.get("daily") or {}):
            daily = item["daily"]
        ck = cache_key("wetter", h["lat"], h["lon"], sat, sun)
        cache_set(ck, daily, CONFIG["cache"]["wetter_ttl"])
        results[hut_idx] = daily

    return results
