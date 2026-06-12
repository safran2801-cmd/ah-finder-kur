"""Orchestrierung der kompletten Suche (Overpass -> Wetter -> Anreicherung).

Wenn curated_huts.json im Projektverzeichnis vorhanden ist, wird diese
vorgeprüfte Liste verwendet (URLs validiert, Wikipedia vorangereichert).
Andernfalls wird live von Overpass geladen.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, List, Optional

from .ai import build_recommendation
from .config import CONFIG
from .geo import country_name, region_from_lonlat
from .overpass import fetch_huts as _fetch_huts_live
from .website import find_official_website
from .weather import fetch_weather_for_huts, score_weather
from .wikipedia import fetch_wikipedia

_CURATED_PATH = Path(__file__).resolve().parent.parent / "curated_huts.json"


def fetch_huts() -> dict:
    """Lädt Hütten – bevorzugt aus curated_huts.json, sonst live von Overpass."""
    if _CURATED_PATH.exists():
        try:
            data = json.loads(_CURATED_PATH.read_text(encoding="utf-8"))
            huts = data.get("huts") or []
            if huts:
                meta = data.get("meta", {})
                return {
                    "huts": huts,
                    "fallback": False,
                    "error": "",
                    "curated": True,
                    "curated_at": meta.get("generated_at", ""),
                }
        except Exception:
            pass  # Bei Fehler auf Live-Abfrage zurückfallen
    return _fetch_huts_live()


class PipelineError(RuntimeError):
    pass


def _enrich_one(h: dict, w: dict, sat_label: str, sun_label: str) -> dict:
    # Kuratierte Hütten haben vorangereicherte und validierte Daten –
    # Wikipedia und Website müssen nicht nochmals abgefragt werden.
    if h.get("wikipediaUrl") is not None or h.get("curatedWebsiteUrl") is not None:
        wiki_url   = h.get("wikipediaUrl")
        wiki_image = h.get("wikipediaImage")
        wiki_text  = h.get("wikipediaText")
        wiki_obj   = {"url": wiki_url, "image": wiki_image, "extract": wiki_text} if wiki_url else None
        website    = h.get("curatedWebsiteUrl") or h.get("website")
    else:
        wiki_obj = fetch_wikipedia(h)
        website  = find_official_website(h)
        wiki_url   = (wiki_obj or {}).get("url")
        wiki_image = (wiki_obj or {}).get("image")
        wiki_text  = (wiki_obj or {}).get("extract")

    rec = build_recommendation(h, w, wiki_obj, sat_label, sun_label)
    return {
        "rank": 0,
        "name": h["name"],
        "lat": h["lat"],
        "lon": h["lon"],
        "elevation": h.get("ele"),
        "region": h.get("__region") or region_from_lonlat(float(h["lat"]), float(h["lon"])),
        "country": country_name(h["country"]),
        "countryCode": h["country"],
        "operator": h.get("operator"),
        "websiteUrl": website,
        "reservationUrl": website,
        "routingUrl": f"https://www.openstreetmap.org/directions?to={h['lat']},{h['lon']}",
        "wikipediaUrl": wiki_url,
        "wikipediaImage": wiki_image,
        "wikipediaText": wiki_text,
        "weather": w,
        "recommendation": rec,
    }


def run_search(sat: str, sun: str, progress: Optional[Callable[[str], None]] = None) -> dict:
    def step(msg: str) -> None:
        if progress:
            progress(msg)

    step("Lade Huettenliste von OpenStreetMap ...")
    huts_resp = fetch_huts()
    huts_all = huts_resp.get("huts") or []
    if not huts_all:
        raise PipelineError("Keine Huetten gefunden")

    huts_top = huts_all[: CONFIG["max_huetten_weather"]]

    step(f"Hole Wetter fuer {len(huts_top)} Huetten ...")
    weather_by_hut = fetch_weather_for_huts(huts_top, sat, sun)

    step("Bewerte Wetter ...")
    scored: List[dict] = []
    for i, h in enumerate(huts_top):
        daily = weather_by_hut[i]
        score = score_weather(daily or {}, sat, sun) if daily else None
        if not score:
            continue
        h2 = dict(h)
        h2["__region"] = region_from_lonlat(float(h["lat"]), float(h["lon"]))
        h2["__weather"] = score
        scored.append({"hut": h2, "score": score["total"]})

    if not scored:
        raise PipelineError("Wetterdaten nicht abrufbar")

    scored.sort(key=lambda x: x["score"], reverse=True)
    top = scored[: CONFIG["top_n"]]

    sat_label = _format_label(sat)
    sun_label = _format_label(sun)

    step(f"Anreicherung fuer {len(top)} Top-Huetten (parallel) ...")
    enriched: List[dict] = []
    with ThreadPoolExecutor(max_workers=min(6, len(top))) as ex:
        futures = [
            ex.submit(_enrich_one, row["hut"], row["hut"]["__weather"], sat_label, sun_label)
            for row in top
        ]
        for fut in futures:
            try:
                enriched.append(fut.result())
            except Exception as e:  # noqa: BLE001
                enriched.append({
                    "name": "?",
                    "error": str(e),
                })

    enriched = [e for e in enriched if "name" in e and "error" not in e]
    enriched.sort(key=lambda r: r.get("weather", {}).get("total", 0), reverse=True)
    for idx, item in enumerate(enriched, start=1):
        item["rank"] = idx

    return {
        "ok": True,
        "weekend": {
            "sat": sat,
            "sun": sun,
            "satLabel": sat_label,
            "sunLabel": sun_label,
        },
        "count": len(enriched),
        "huts": enriched,
        "fallback": huts_resp.get("fallback", False),
        "fallbackReason": huts_resp.get("error", ""),
    }


def _format_label(d: str) -> str:
    from datetime import datetime
    try:
        return datetime.strptime(d, "%Y-%m-%d").strftime("%d.%m.%Y")
    except ValueError:
        return d
