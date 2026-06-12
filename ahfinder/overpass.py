"""Hüttenliste von der Overpass-API (OpenStreetMap)."""
from __future__ import annotations

import json
import re
import time
from typing import List
from urllib.parse import urlencode

from .cache import cache_get, cache_set
from .config import CONFIG, cache_key
from .geo import country_from_lonlat
from .http import http_post


def _sort_key(h: dict) -> int:
    return (
        (3 if h.get("operator") else 0)
        + (2 if h.get("website") else 0)
        + (3 if h.get("wikidata") else 0)
        + (2 if h.get("wikipedia") else 0)
        + (2 if (h.get("capacity") or 0) >= 20 else 0)
    )


def _extract_overpass_error(body: str | None) -> str:
    """Versucht die eigentliche Fehlermeldung aus einer Overpass-Antwort zu extrahieren."""
    if not body:
        return ""
    if m := re.search(r"<strong[^>]*>\s*Error\s*</strong>\s*:\s*([^<]+)", body):
        return m.group(1).strip()
    if m := re.search(r'"remark"\s*:\s*"([^"]+)"', body):
        return m.group(1).strip()
    return body[:200].replace("\n", " ").strip()


def _try_query(endpoints: list, query: str, timeout: int, max_attempts: int = 2) -> tuple:
    """Probiert Endpoints + Retries. Liefert (data, error_message)."""
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


def fetch_huts() -> dict:
    """Liefert {'huts': [...], 'fallback': bool, 'error': str}."""
    bbox = CONFIG["overpass_bbox"]
    key = cache_key(
        "huetten_v1",
        bbox["south"], bbox["west"], bbox["north"], bbox["east"],
    )
    cached = cache_get(key)
    if cached is not None:
        return {"huts": cached, "fallback": False, "error": ""}

    query = (
        f"[out:json][timeout:{CONFIG['overpass']['timeout']}];\n"
        "(\n"
        f'  node["tourism"="alpine_hut"]["name"]'
        f'({bbox["south"]:.4f},{bbox["west"]:.4f},{bbox["north"]:.4f},{bbox["east"]:.4f});\n'
        f'  way["tourism"="alpine_hut"]["name"]'
        f'({bbox["south"]:.4f},{bbox["west"]:.4f},{bbox["north"]:.4f},{bbox["east"]:.4f});\n'
        f'  relation["tourism"="alpine_hut"]["name"]'
        f'({bbox["south"]:.4f},{bbox["west"]:.4f},{bbox["north"]:.4f},{bbox["east"]:.4f});\n'
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
        from .static_huts import get_static_huts
        return {
            "huts": get_static_huts(),
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

        key2 = f"{name.lower()}|{round(lat, 3)}|{round(lon, 3)}"
        if key2 in seen:
            continue
        seen.add(key2)

        huts.append({
            "osm_id": f"{el.get('type', 'node')}/{el['id']}",
            "name": name,
            "lat": round(float(lat), 5),
            "lon": round(float(lon), 5),
            "ele": int(tags["ele"]) if tags.get("ele") else None,
            "operator": tags.get("operator"),
            "website": tags.get("website") or tags.get("contact:website"),
            "reservation": tags.get("reservation"),
            "phone": tags.get("phone") or tags.get("contact:phone"),
            "wikidata": tags.get("wikidata"),
            "wikipedia": tags.get("wikipedia"),
            "capacity": int(tags["capacity"]) if tags.get("capacity") else 0,
            "country": country_from_lonlat(float(lat), float(lon)),
            "shelter": tags.get("shelter_type"),
        })

    huts.sort(key=_sort_key, reverse=True)
    cache_set(key, huts, CONFIG["cache"]["huetten_ttl"])
    return {"huts": huts, "fallback": False, "error": ""}
