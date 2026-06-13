"""SAC-Tourenportal: tagesgenaue Bettenverfügbarkeit via huts-middleware API.

Zwei-Schritt-Prozess:
1. SAC-Tourenportal-Seite laden → hutId aus data-hutreservation-options extrahieren
2. POST an huts-middleware API → Verfügbarkeit für die nächsten 14 Tage

Liefert ein Dict wie:
{
  "2026-06-14": {"status": "available", "freePlaces": 8},
  "2026-06-13": {"status": "booked",    "freePlaces": 0},
  ...
}
oder None wenn die Hütte nicht im Mapping / kein Reservierungssystem vorhanden.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .cache import cache_get, cache_set
from .config import CONFIG, cache_key
from .http import http_get, http_post

_AVAILABILITY_API = "https://huts-middleware.web.sac-cas.ch/api/hutsAvailability"
_MAPPING_PATH = Path(__file__).resolve().parent.parent / "sac_hut_mapping.json"
_SAC_MAPPING: Optional[dict] = None


def _get_mapping() -> dict:
    global _SAC_MAPPING
    if _SAC_MAPPING is None:
        try:
            _SAC_MAPPING = json.loads(
                _MAPPING_PATH.read_text(encoding="utf-8-sig")
            )
        except Exception:
            _SAC_MAPPING = {}
    return _SAC_MAPPING


def find_portal_url(hut_name: str) -> Optional[str]:
    """Findet die SAC-Tourenportal-URL für einen Hüttennamen.

    Versucht: exakter Match → case-insensitiv → Teilstring.
    """
    mapping = _get_mapping()
    if hut_name in mapping:
        return mapping[hut_name]
    lower = hut_name.lower()
    for key, url in mapping.items():
        if key.lower() == lower:
            return url
    for key, url in mapping.items():
        if lower in key.lower() or key.lower() in lower:
            return url
    return None


def _get_hut_middleware_id(portal_url: str) -> Optional[int]:
    """Extrahiert die interne hutId aus der SAC-Tourenportal-Seite (statisches HTML)."""
    ck = cache_key("hut_middleware_id", portal_url)
    cached = cache_get(ck)
    if cached is not None:
        return int(cached) if cached else None

    r = http_get(portal_url, timeout=10)
    if r["code"] != 200 or not r["body"]:
        return None

    # Suche: "hutId":312 direkt im HTML (server-gerendered, kein JS nötig)
    m = re.search(r'"hutId"\s*:\s*(\d+)', r["body"])
    if not m:
        cache_set(ck, False, CONFIG["cache"]["huetten_ttl"])
        return None

    hut_id = int(m.group(1))
    cache_set(ck, hut_id, CONFIG["cache"]["huetten_ttl"])
    return hut_id


def fetch_hut_availability(hut_name: str) -> Optional[dict]:
    """Holt die tagesgenaue Verfügbarkeit einer SAC-Hütte (nächste 14 Tage).

    Gibt None zurück wenn die Hütte nicht im Mapping ist oder kein
    Reservierungssystem hat. Ergebnis wird 6 Stunden gecacht.
    """
    ck = cache_key("hut_availability_v2", hut_name.lower().strip())
    cached = cache_get(ck)
    if cached is not None:
        return cached or None

    # Schritt 1: SAC-Tourenportal-URL aus Mapping
    portal_url = find_portal_url(hut_name)
    if not portal_url:
        cache_set(ck, False, CONFIG["cache"]["huetten_ttl"])
        return None

    # Schritt 2: interne hutId aus der Seite lesen
    hut_id = _get_hut_middleware_id(portal_url)
    if not hut_id:
        cache_set(ck, False, CONFIG["cache"]["huetten_ttl"])
        return None

    # Schritt 3: Availability-API aufrufen
    today = datetime.now()
    end = today + timedelta(days=14)
    payload = {
        "startDate": today.strftime("%d.%m.%Y"),
        "endDate": end.strftime("%d.%m.%Y"),
        "numOfPeople": 1,
        "page": 0,
        "onlyAvailablePlaces": False,
        "huts": [hut_id],
    }
    r = http_post(_AVAILABILITY_API, payload, timeout=10)
    if r["code"] != 200 or not r["body"]:
        return None

    try:
        data = json.loads(r["body"])
    except json.JSONDecodeError:
        return None

    huts_avail = data.get("hutsAvailability") or []
    if not huts_avail:
        return None

    result = {}
    for day in huts_avail[0].get("calendarDays", []):
        day_str = day.get("day", "")          # Format: "13.06.2026"
        status_raw = day.get("status", "")
        try:
            iso = datetime.strptime(day_str, "%d.%m.%Y").date().isoformat()
        except ValueError:
            continue
        free_places = sum(
            cat.get("totalFreePlaces", 0)
            for cat in day.get("bedCategoriesData", [])
        )
        result[iso] = {
            "status": "available" if status_raw == "RESERVATION_POSSIBLE" else "booked",
            "freePlaces": free_places,
        }

    if not result:
        cache_set(ck, False, CONFIG["cache"]["huetten_ttl"])
        return None

    cache_set(ck, result, 6 * 3600)
    return result
