"""Hüttenliste Schweiz – gefilterte Overpass-Abfrage (nur CH, SAC priorisiert)."""
from __future__ import annotations

import json
import re
import time
from typing import List
from urllib.parse import urlencode

from .cache import cache_get, cache_set
from .config import CONFIG, cache_key
from .http import http_post
from .sac_info import _find_tourenportal_url

# Bounding Box Schweiz (inkl. kleiner Puffer)
CH_BBOX = {
    "south": 45.82,
    "west":   5.96,
    "north": 47.82,
    "east":  10.50,
}

# SAC-Buchungsportal – Fallback wenn keine eigene Website bekannt
# HINWEIS: Die alte URL (.../huetten-und-kletteranlagen/huettenverzeichnis/) ist
# tot - sie taucht in der aktuellen sac-cas.ch Navigation nicht mehr auf und
# liefert nur eine leere Redirect-Antwort. Aktueller "Eine Hütte finden"-Link:
SAC_DIRECTORY_URL = (
    "https://www.sac-cas.ch/de/huetten-und-touren/sac-tourenportal/?type=hut"
)


def _is_ch(tags: dict, lat: float, lon: float) -> bool:
    """Gibt True zurück wenn die Hütte in der Schweiz liegt.

    Zweite Sicherheitsstufe: Die Overpass-Abfrage filtert bereits über die
    echte Landesflaeche (area["ISO3166-1"="CH"]), trotzdem kann der von
    Overpass gelieferte "center"-Punkt von Ways/Relations, die direkt auf
    der Grenze liegen, knapp ausserhalb fallen. Die Bbox-Pruefung dient nur
    noch als grobe Plausibilitaetspruefung, NICHT als primaerer Laenderfilter
    (eine Bbox kann die unregelmaessige CH-Grenze ohnehin nie exakt abbilden).
    """
    country_tag = (tags.get("addr:country") or "").upper()
    if country_tag:
        return country_tag == "CH"
    # Liechtenstein (lon 9.47–9.64, lat 47.05–47.27) ausschliessen
    if 9.47 < lon < 9.65 and 47.04 < lat < 47.28:
        return False
    # Einfache Bounding-Box-Prüfung als Fallback
    return (
        CH_BBOX["south"] <= lat <= CH_BBOX["north"]
        and CH_BBOX["west"] <= lon <= CH_BBOX["east"]
    )


def _sac_sort_key(h: dict) -> int:
    """Sortiergewicht: SAC-Hütten und gut dokumentierte Einträge oben."""
    op = (h.get("operator") or "").upper()
    sac_bonus = 5 if "SAC" in op or "CAS" in op else 0
    return (
        sac_bonus
        + (3 if h.get("operator") else 0)
        + (2 if h.get("website") else 0)
        + (3 if h.get("wikidata") else 0)
        + (2 if h.get("wikipedia") else 0)
        + (2 if (h.get("capacity") or 0) >= 20 else 0)
    )


def _extract_overpass_error(body: str | None) -> str:
    if not body:
        return ""
    if m := re.search(r"<strong[^>]*>\s*Error\s*</strong>\s*:\s*([^<]+)", body):
        return m.group(1).strip()
    if m := re.search(r'"remark"\s*:\s*"([^"]+)"', body):
        return m.group(1).strip()
    return body[:200].replace("\n", " ").strip()


def _try_query(endpoints: list, query: str, timeout: int, max_attempts: int = 2) -> tuple:
    last_err = ""
    for ep in endpoints:
        for attempt in range(1, max_attempts + 1):
            r = http_post(
                ep,
                urlencode({"data": query}),
                timeout,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if r["code"] == 200 and r["body"]:
                try:
                    j = json.loads(r["body"])
                except json.JSONDecodeError:
                    j = None
                if isinstance(j, dict) and "elements" in j:
                    return j, ""
                last_err = _extract_overpass_error(r["body"]) or f"HTTP {r['code']}"
            else:
                last_err = r["error"] or f"HTTP {r['code']}"
                if r["body"]:
                    last_err += f" - {_extract_overpass_error(r['body'])}"
            if attempt < max_attempts:
                time.sleep(1.5 * attempt)
    return None, last_err


def fetch_huts_ch() -> dict:
    """Liefert {'huts': [...], 'fallback': bool, 'error': str} – nur Schweizer Hütten."""
    # v2: Abfrage ueber die echte Landesflaeche (Overpass "area"-Filter anhand
    # ISO3166-1=CH) statt einer rechteckigen Bounding-Box. Eine Bbox um die
    # Schweiz reicht zwangslaeufig weit nach Frankreich, Italien, Deutschland
    # und Oesterreich hinein (die Schweiz ist laenglich/unregelmaessig geformt),
    # wodurch zuvor hunderte auslaendische Huetten faelschlich als "Schweizer
    # Huetten" eingestuft wurden (~800 statt der erwarteten ~150).
    key = cache_key("huetten_ch_v2", "iso=CH", "admin_level=2")
    cached = cache_get(key)
    if cached is not None:
        return {"huts": cached, "fallback": False, "error": ""}

    query = (
        f"[out:json][timeout:{CONFIG['overpass']['timeout']}];\n"
        'area["ISO3166-1"="CH"]["admin_level"="2"]->.ch;\n'
        "(\n"
        '  node["tourism"="alpine_hut"]["name"](area.ch);\n'
        '  way["tourism"="alpine_hut"]["name"](area.ch);\n'
        '  relation["tourism"="alpine_hut"]["name"](area.ch);\n'
        ");\n"
        "out center tags;"
    )

    endpoints = [CONFIG["overpass"]["endpoint"]]
    for fb in CONFIG["overpass"].get("fallbacks", []):
        endpoints.append(fb)
    if CONFIG["overpass"].get("fallback") and CONFIG["overpass"]["fallback"] not in endpoints:
        endpoints.append(CONFIG["overpass"]["fallback"])

    data, err = _try_query(endpoints, query, CONFIG["overpass"]["timeout"], max_attempts=1)

    if data is None:
        from .static_huts_ch import get_static_huts_ch
        return {
            "huts": get_static_huts_ch(),
            "fallback": True,
            "error": err,
        }

    huts: List[dict] = []
    seen: set = set()
    for el in data.get("elements", []):
        tags = el.get("tags") or {}
        name = (tags.get("name") or "").strip()
        if not name:
            continue

        lat = el.get("lat") or (el.get("center") or {}).get("lat")
        lon = el.get("lon") or (el.get("center") or {}).get("lon")
        if lat is None or lon is None:
            continue

        lat, lon = float(lat), float(lon)

        # Nur Schweizer Hütten behalten
        if not _is_ch(tags, lat, lon):
            continue

        key2 = f"{name.lower()}|{round(lat, 3)}|{round(lon, 3)}"
        if key2 in seen:
            continue
        seen.add(key2)

        # SAC-Buchungslink: eigene Website bevorzugen, sonst SAC-Tourenportal-Detail-Seite
        website_raw = tags.get("website") or tags.get("contact:website") or ""
        operator = tags.get("operator") or ""
        is_sac = "SAC" in operator.upper() or "CAS" in operator.upper()

        # Für SAC-Hütten ohne Website: versuche die exakte SAC-Tourenportal-Detail-Seite zu finden
        # Falls nicht gefunden: Fallback zur generischen Übersicht
        sac_booking = None
        if is_sac and not website_raw:
            portal_url = _find_tourenportal_url(name)
            if portal_url:
                sac_booking = portal_url
            else:
                sac_booking = SAC_DIRECTORY_URL

        has_contact_signal = bool(
            website_raw
            or sac_booking
            or tags.get("reservation")
            or tags.get("phone")
            or tags.get("contact:phone")
        )
        if not has_contact_signal:
            continue

        huts.append({
            "osm_id": f"{el.get('type', 'node')}/{el['id']}",
            "name": name,
            "lat": round(lat, 5),
            "lon": round(lon, 5),
            "ele": int(tags["ele"]) if tags.get("ele") else None,
            "operator": operator or None,
            "website": website_raw or None,
            "sac_booking": sac_booking,
            "is_sac": is_sac,
            "reservation": tags.get("reservation"),
            "phone": tags.get("phone") or tags.get("contact:phone"),
            "wikidata": tags.get("wikidata"),
            "wikipedia": tags.get("wikipedia"),
            "capacity": int(tags["capacity"]) if tags.get("capacity") else 0,
            "country": "CH",
            "shelter": tags.get("shelter_type"),
        })

    huts.sort(key=_sac_sort_key, reverse=True)
    cache_set(key, huts, CONFIG["cache"]["huetten_ttl"])
    return {"huts": huts, "fallback": False, "error": ""}
