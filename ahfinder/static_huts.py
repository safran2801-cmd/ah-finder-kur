"""Statische Hüttenliste als Fallback, falls Overpass nicht erreichbar ist.

Koordinaten und Hoehen sind ungefaehr, sollten aber fuer Wetter,
Wikipedia-Lookup und Kartenzuordnung genau genug sein. Die Liste
kann beliebig erweitert werden - weitere Felder (wikidata, website,
operator) beschleunigen die Anreicherung, sind aber nicht noetig,
weil pipeline.py fehlende Werte via Wikidata/DuckDuckGo ergaenzt.
"""
from __future__ import annotations

from typing import List

STATIC_HUTS: List[dict] = [
    # ── DE: Bayerische Alpen ──────────────────────────────────────────────
    {"name": "Tegernseer Huette",     "lat": 47.4483, "lon": 11.4536, "ele": 1650, "operator": "DAV Sektion Tegernsee"},
    {"name": "Hoellentalangerhuette", "lat": 47.4383, "lon": 11.0217, "ele": 1381, "operator": "DAV Sektion Muenchen"},
    {"name": "Watzmannhaus",          "lat": 47.5717, "lon": 12.9333, "ele": 1930, "operator": "DAV Sektion Berchtesgaden"},
    {"name": "Rappenseehuette",       "lat": 47.2817, "lon": 10.2517, "ele": 2091, "operator": "DAV Sektion Allgaeu-Immenstadt"},
    {"name": "Kemptner Huette",       "lat": 47.3283, "lon": 10.3317, "ele": 1844, "operator": "DAV Sektion Allgaeu-Kempten"},
    {"name": "Muenchner Haus",        "lat": 47.4150, "lon": 10.9850, "ele": 2959, "operator": "DAV Sektion Muenchen"},
    {"name": "Knorrhuette",           "lat": 47.4100, "lon": 11.0217, "ele": 2052, "operator": "DAV Sektion Muenchen"},
    {"name": "Blaueishuette",         "lat": 47.5783, "lon": 12.8717, "ele": 1651, "operator": "DAV Sektion Berchtesgaden"},
    {"name": "Staufner Haus",         "lat": 47.5083, "lon": 10.0250, "ele": 1620, "operator": "DAV Sektion Oberstdorf"},
    {"name": "Mittenwalder Huette",   "lat": 47.3383, "lon": 11.3517, "ele": 1515, "operator": "DAV Sektion Mittenwald"},
    {"name": "Soiernhaus",            "lat": 47.4917, "lon": 11.3717, "ele": 1616, "operator": "DAV Sektion Mittenwald"},
    {"name": "Meilerhuette",          "lat": 47.5417, "lon": 10.9617, "ele": 1835, "operator": "DAV Sektion Garmisch-Partenkirchen"},

    # ── AT: Tiroler / Salzburger Alpen ────────────────────────────────────
    {"name": "Brandenburger Huette",     "lat": 47.0817, "lon": 12.6833, "ele": 2134, "operator": "DAV Sektion Berlin"},
    {"name": "Heinrich-Schwaiger-Haus",  "lat": 47.1317, "lon": 12.6833, "ele": 2802, "operator": "OeAV Sektion Salzburg"},
    {"name": "Kuersinger Huette",        "lat": 47.1650, "lon": 12.6750, "ele": 2548, "operator": "OeAV Sektion Salzburg"},
    {"name": "Neue Prager Huette",       "lat": 47.1617, "lon": 12.6833, "ele": 2796, "operator": "OeAV Sektion Prag"},
    {"name": "Simonyhuette",             "lat": 47.4717, "lon": 13.4917, "ele": 2205, "operator": "OeAV Sektion Austria"},
    {"name": "Hofpuerglhuette",          "lat": 47.4967, "lon": 13.4917, "ele": 1705, "operator": "OeAV Sektion Salzburg"},
    {"name": "Adameqhuette",             "lat": 47.1983, "lon": 12.6850, "ele": 2196, "operator": "OeAV Sektion Austria"},
    {"name": "Wolayerseehuette",         "lat": 46.6267, "lon": 12.8817, "ele": 1962, "operator": "OeAV Sektion Wolayersee"},
    {"name": "Elberfelder Huette",       "lat": 47.1717, "lon": 12.4833, "ele": 2346, "operator": "DAV Sektion Wuppertal"},
    {"name": "Defreggerhaus",            "lat": 47.0783, "lon": 12.3583, "ele": 2962, "operator": "OeAV Sektion Austria"},
    {"name": "Sudetendeutsche Huette",   "lat": 47.1717, "lon": 12.5033, "ele": 2650, "operator": "DAV Sektion Sudeten"},

    # ── CH: Schweizer Alpen ───────────────────────────────────────────────
    {"name": "Gaulihuette",          "lat": 46.5167, "lon":  8.1500, "ele": 2205, "operator": "SAC Sektion Basel"},
    {"name": "Schreckhornhuette",    "lat": 46.5900, "lon":  8.1183, "ele": 2530, "operator": "SAC Sektion Grindelwald"},
    {"name": "Finsteraarhornhuette", "lat": 46.5383, "lon":  8.1183, "ele": 2448, "operator": "SAC Sektion Grindelwald"},
    {"name": "Glecksteinhuette",     "lat": 46.6333, "lon":  8.0833, "ele": 2317, "operator": "SAC Sektion Grindelwald"},
    {"name": "Dossenhuette",         "lat": 46.6333, "lon":  8.0200, "ele": 1883, "operator": "SAC Sektion Bern"},
    {"name": "Trifthuette",          "lat": 46.6917, "lon":  8.3717, "ele": 2520, "operator": "SAC Sektion Bern"},

    # ── IT: Dolomiten / Italienische Alpen ────────────────────────────────
    {"name": "Rifugio Locatelli",    "lat": 46.6417, "lon": 12.3200, "ele": 2405, "operator": "CAI Sezione di Padova"},
    {"name": "Rifugio Lagazuoi",     "lat": 46.5217, "lon": 12.0017, "ele": 2750, "operator": "CAI Sezione di Cortina"},
    {"name": "Rifugio Vajolet",      "lat": 46.4617, "lon": 11.6350, "ele": 2243, "operator": "SAT"},
    {"name": "Rifugio Bolzano",      "lat": 46.6717, "lon": 11.7317, "ele": 1225, "operator": "CAI Sezione di Bolzano"},
    {"name": "Rifugio Auronzo",      "lat": 46.6167, "lon": 12.3333, "ele": 2333, "operator": "CAI Sezione di Auronzo"},
    {"name": "Rifugio Brentei",      "lat": 46.1817, "lon": 10.8800, "ele": 2182, "operator": "SAT"},
    {"name": "Rifugio Tuckett",      "lat": 46.1717, "lon": 10.8717, "ele": 2272, "operator": "SAT"},

    # ── FR: Französische Alpen ────────────────────────────────────────────
    {"name": "Refuge du Gouter",       "lat": 45.8517, "lon":  6.8150, "ele": 3815, "operator": "FFCAM Club Alpin Francais"},
    {"name": "Refuge des Cosmiques",   "lat": 45.8733, "lon":  6.8867, "ele": 3613, "operator": "FFCAM Club Alpin Francais"},
    {"name": "Refuge de la Pilatte",   "lat": 44.8833, "lon":  6.3500, "ele": 2572, "operator": "FFCAM Club Alpin Francais"},
    {"name": "Refuge du Promontoire",  "lat": 44.9183, "lon":  6.3550, "ele": 2584, "operator": "FFCAM Club Alpin Francais"},
    {"name": "Refuge de l'Aigle",      "lat": 45.8717, "lon":  6.9017, "ele": 3450, "operator": "FFCAM Club Alpin Francais"},
]


def get_static_huts() -> List[dict]:
    """Liefert die statische H\u00fcttenliste im Format von fetch_huts()."""
    from .geo import country_from_lonlat

    out: List[dict] = []
    for i, h in enumerate(STATIC_HUTS, start=1):
        out.append({
            "osm_id": f"static/{i}",
            "name": h["name"],
            "lat": round(float(h["lat"]), 5),
            "lon": round(float(h["lon"]), 5),
            "ele": int(h["ele"]) if h.get("ele") else None,
            "operator": h.get("operator"),
            "website": None,
            "reservation": None,
            "phone": None,
            "wikidata": None,
            "wikipedia": None,
            "capacity": 0,
            "country": country_from_lonlat(float(h["lat"]), float(h["lon"])),
            "shelter": None,
        })
    return out
