"""Pipeline Schweizer Hütten (Overpass CH -> Wetter -> Anreicherung).

Wenn curated_huts.json im Projektverzeichnis vorhanden ist, wird diese
kuratierte Liste als Hütten-Quelle verwendet (statt Live-Overpass-Abfrage).
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, List, Optional

from .ai import build_recommendation
from .config import CONFIG
from .geo import region_from_lonlat
from .overpass_ch import SAC_DIRECTORY_URL, fetch_huts_ch

_CURATED_PATH = Path(__file__).resolve().parent.parent / "curated_huts.json"


def _load_huts() -> dict:
    """Lädt Hütten – bevorzugt aus curated_huts.json, sonst live von Overpass."""
    if _CURATED_PATH.exists():
        try:
            meta = json.loads(_CURATED_PATH.read_text(encoding="utf-8"))
            huts = meta.get("huts") or []
            if huts:
                return {
                    "huts": [
                        {**h, "curated": True, "curated_at": meta.get("generated_at", "")}
                        for h in huts
                    ],
                    "fallback": False,
                    "error": "",
                }
        except Exception:
            pass
    return fetch_huts_ch()
from .sac_info import fetch_sac_season_info, find_sac_official_website
from .website import find_official_website
from .weather import fetch_weather_for_huts, score_weather
from .wikipedia import fetch_wikipedia


class PipelineError(RuntimeError):
    pass


def _enrich_batch(rows: List[dict], sat_label: str, sun_label: str) -> List[dict]:
    enriched: List[dict] = []
    if not rows:
        return enriched

    with ThreadPoolExecutor(max_workers=min(6, len(rows))) as ex:
        futures = [
            ex.submit(
                _enrich_one_ch,
                row["hut"],
                row["hut"]["__weather"],
                sat_label,
                sun_label,
            )
            for row in rows
        ]
        for fut in futures:
            try:
                enriched.append(fut.result())
            except Exception as e:  # noqa: BLE001
                enriched.append({"name": "?", "error": str(e)})

    return [item for item in enriched if "name" in item and "error" not in item]


def _enrich_one_ch(h: dict, w: dict, sat_label: str, sun_label: str) -> dict:
    wiki = fetch_wikipedia(h)

    website = h.get("website")
    if not website and h.get("is_sac"):
        website = find_sac_official_website(h["name"], h.get("sac_booking"))
    if not website:
        website = find_official_website(h)

    sac_url = h.get("sac_booking") or (
        SAC_DIRECTORY_URL if h.get("is_sac") and not website else None
    )
    season = fetch_sac_season_info(h["name"]) if h.get("is_sac") else None
    rec = build_recommendation(h, w, wiki, sat_label, sun_label)

    return {
        "rank": 0,
        "name": h["name"],
        "lat": h["lat"],
        "lon": h["lon"],
        "elevation": h.get("ele"),
        "region": h.get("__region")
        or region_from_lonlat(float(h["lat"]), float(h["lon"])),
        "country": "Schweiz",
        "countryCode": "CH",
        "operator": h.get("operator"),
        "isSac": h.get("is_sac", False),
        "websiteUrl": website,
        "sacBookingUrl": sac_url,
        "reservationUrl": website or sac_url,
        "routingUrl": f"https://www.openstreetmap.org/directions?to={h['lat']},{h['lon']}",
        "wikipediaUrl": (wiki or {}).get("url"),
        "wikipediaImage": (wiki or {}).get("image"),
        "wikipediaText": (wiki or {}).get("extract"),
        "seasonInfo": season,
        "availability": None,
        "weather": w,
        "recommendation": rec,
    }


def run_search_ch(
    sat: str,
    sun: str,
    only_photos: bool = False,
    progress: Optional[Callable[[str], None]] = None,
) -> dict:
    def step(msg: str) -> None:
        if progress:
            progress(msg)

    if _CURATED_PATH.exists():
        step("Lade kuratierte Hütten-Liste (curated_huts.json) ...")
    else:
        step("Lade Schweizer Hütten von OpenStreetMap ...")
    huts_resp = _load_huts()
    huts_all = huts_resp.get("huts") or []
    if not huts_all:
        raise PipelineError("Keine Schweizer Hütten gefunden")

    huts_top = huts_all[: CONFIG["max_huetten_weather"]]

    step(
        f"Hole Wetterdaten für alle {len(huts_top)} Hütten via Batch-Request (Open-Meteo) ..."
    )
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

    sat_label = _format_label(sat)
    sun_label = _format_label(sun)

    target_enrich_n = min(CONFIG["enrich_n"], len(scored))
    max_enrich_n = target_enrich_n
    batch_size = target_enrich_n
    target_photo_n = 0

    if only_photos:
        max_enrich_n = min(CONFIG["photo_enrich_n_max"], len(scored))
        batch_size = max(1, CONFIG["photo_enrich_batch_size"])
        target_photo_n = CONFIG["top_n"]

    step(f"Anreicherung für zunächst {target_enrich_n} Top-Hütten ...")
    enriched: List[dict] = []
    cursor = 0

    while cursor < max_enrich_n:
        next_cursor = min(
            max_enrich_n,
            target_enrich_n if cursor == 0 else cursor + batch_size,
        )
        enriched.extend(_enrich_batch(scored[cursor:next_cursor], sat_label, sun_label))
        cursor = next_cursor

        if not only_photos:
            break

        photo_count = sum(1 for item in enriched if item.get("wikipediaImage"))
        if len(enriched) >= target_enrich_n and photo_count >= target_photo_n:
            break

        if cursor < max_enrich_n:
            step(
                f"Zu wenige Bildtreffer ({photo_count}/{target_photo_n}) - "
                "prüfe weitere Wetter-Kandidaten ..."
            )

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
