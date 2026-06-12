#!/usr/bin/env python3
"""
curator.py – Wöchentlicher Kurations-Job für den Alpen Hütten-Finder.

Ablauf:
  1. Hütten von der Overpass-API laden (gleiche Abfrage wie Haupt-App)
  2. Top 300 nach Qualitätsscore auswählen
  3. Für jede Hütte intensiv anreichern:
     - Website-URL validieren (erreichbar? HTTP 200?)
     - Wikipedia / Wikidata Bild + Text laden
     - Offizielle Website ermitteln falls kein OSM-Tag
  4. Ergebnis als curated_huts.json speichern

Ausführung:
  python curator.py              # alle 300 Hütten
  python curator.py --limit 20  # Schnelltest mit 20 Hütten
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Bestehende Module wiederverwenden
from ahfinder.overpass_ch import fetch_huts_ch as fetch_huts
from ahfinder.http import http_get
from ahfinder.wikipedia import fetch_wikipedia
from ahfinder.website import find_official_website
from ahfinder.config import CONFIG

OUT_FILE = Path(__file__).parent / "curated_huts.json"
MAX_HUTS = 300
MAX_WORKERS = 8
REQUEST_TIMEOUT = 8


# ── URL-Validierung ────────────────────────────────────────────────────────────

def validate_url(url: Optional[str]) -> Optional[str]:
    """Prüft ob eine URL erreichbar ist. Gibt die URL zurück oder None."""
    if not url:
        return None
    try:
        r = http_get(url, timeout=REQUEST_TIMEOUT)
        if r["code"] in (200, 301, 302, 303, 307, 308):
            return url
        # Manche Seiten antworten nur auf GET, nicht HEAD – nochmal versuchen
        if r["code"] in (405, 0):
            r2 = http_get(url, timeout=REQUEST_TIMEOUT)
            if r2["code"] and r2["code"] < 400:
                return url
        print(f"  ✗ URL ungültig ({r['code']}): {url}")
        return None
    except Exception as e:
        print(f"  ✗ URL Fehler: {url} – {e}")
        return None


# ── Anreicherung einer einzelnen Hütte ────────────────────────────────────────

def enrich_hut(h: dict) -> dict:
    """Reichert eine Hütte mit Wikipedia, Website und URL-Check an."""
    name = h["name"]

    # Wikipedia (de/fr/it)
    wiki = fetch_wikipedia(h)

    # Offizielle Website (OSM → Wikidata → DuckDuckGo)
    raw_site = find_official_website(h)

    # URL-Validierung
    validated_site = validate_url(raw_site)

    result = dict(h)
    result["curatedWebsiteUrl"] = validated_site
    result["websiteValid"] = validated_site is not None
    result["originalWebsiteUrl"] = raw_site  # zur Nachverfolgung

    if wiki:
        result["wikipediaUrl"]   = wiki.get("url")
        result["wikipediaImage"] = wiki.get("image")
        result["wikipediaText"]  = wiki.get("extract")
        result["wikipediaLang"]  = wiki.get("lang")
    else:
        result["wikipediaUrl"]   = None
        result["wikipediaImage"] = None
        result["wikipediaText"]  = None
        result["wikipediaLang"]  = None

    return result


# ── Hauptlogik ─────────────────────────────────────────────────────────────────

def main(limit: int = MAX_HUTS) -> None:
    start = time.time()
    print(f"\n{'='*60}")
    print(f"  Alpen Hütten-Finder – Kurations-Job")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*60}\n")

    # 1. Hütten laden
    print("1/3  Lade Hüttenliste von OpenStreetMap …")
    resp = fetch_huts()
    all_huts = resp.get("huts") or []
    if not all_huts:
        print("FEHLER: Keine Hütten gefunden!", file=sys.stderr)
        sys.exit(1)

    if resp.get("fallback"):
        print(f"     ⚠ Fallback-Liste verwendet: {resp.get('error', '')}")
    else:
        print(f"     ✓ {len(all_huts)} Hütten geladen")

    # 2. Top N auswählen (nach Qualitätsscore, bereits sortiert)
    huts = all_huts[:limit]
    print(f"\n2/3  Wähle Top {len(huts)} Hütten aus …")

    # 3. Parallel anreichern
    print(f"\n3/3  Reichere {len(huts)} Hütten an (bis zu {MAX_WORKERS} parallel) …\n")
    enriched = []
    failed = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(enrich_hut, h): h for h in huts}
        done = 0
        for fut in as_completed(futures):
            done += 1
            hut = futures[fut]
            try:
                result = fut.result()
                enriched.append(result)
                wiki_ok  = "📖" if result.get("wikipediaImage") else "  "
                site_ok  = "🌐" if result.get("websiteValid")    else "  "
                print(f"  [{done:3d}/{len(huts)}] {wiki_ok}{site_ok}  {hut['name']}")
            except Exception as e:
                failed += 1
                print(f"  [{done:3d}/{len(huts)}] ✗  {hut['name']} – {e}")

    # Nach originalem Qualitätsscore sortiert lassen
    # (Reihenfolge aus Overpass-Abfrage bereits nach Score)

    # Metadaten hinzufügen
    output = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "hut_count": len(enriched),
            "failed": failed,
            "source": "OpenStreetMap Overpass API",
        },
        "huts": enriched,
    }

    OUT_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    elapsed = time.time() - start
    print(f"\n{'='*60}")
    print(f"  ✓ {len(enriched)} Hütten gespeichert → {OUT_FILE.name}")
    wiki_count = sum(1 for h in enriched if h.get("wikipediaImage"))
    site_count = sum(1 for h in enriched if h.get("websiteValid"))
    print(f"  📖 Wikipedia-Bilder: {wiki_count}/{len(enriched)}")
    print(f"  🌐 Validierte URLs:  {site_count}/{len(enriched)}")
    if failed:
        print(f"  ⚠ Fehler:           {failed}")
    print(f"  ⏱ Laufzeit:         {elapsed:.0f}s")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Alpen Hütten-Finder Kurations-Job")
    parser.add_argument("--limit", type=int, default=MAX_HUTS,
                        help=f"Anzahl Hütten (Standard: {MAX_HUTS})")
    args = parser.parse_args()
    main(limit=args.limit)
