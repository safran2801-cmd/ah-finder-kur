"""Geografische Hilfsfunktionen (Land + Region aus Lat/Lon)."""
from __future__ import annotations

from typing import Tuple

COUNTRY_NAMES = {
    "DE": "Deutschland",
    "AT": "Oesterreich",
    "CH": "Schweiz",
    "IT": "Italien",
    "FR": "Frankreich",
    "LI": "Liechtenstein",
}

REGIONS = [
    ("Allgaeuer Alpen",       47.10, 47.55,   9.90, 10.55),
    ("Wettersteingebirge",    47.30, 47.50,  10.85, 11.25),
    ("Berchtesgadener Alpen", 47.40, 47.80,  12.70, 13.20),
    ("Karwendel",             47.25, 47.50,  11.10, 11.65),
    ("Tiroler Alpen",         46.75, 47.65,  10.00, 12.80),
    ("Salzburger Alpen",      47.00, 47.80,  12.50, 13.50),
    ("Kaerntner Alpen",       46.50, 47.20,  12.50, 14.80),
    ("Stubaier Alpen",        46.85, 47.20,  10.90, 11.40),
    ("Oetztaler Alpen",       46.65, 47.15,  10.50, 11.30),
    ("Zillertaler Alpen",     46.85, 47.30,  11.50, 12.30),
    ("Dolomiten",             46.20, 46.70,  11.40, 12.60),
    ("Berner Oberland",       46.30, 46.85,   7.50,  8.50),
    ("Wallis",                45.80, 46.55,   6.80,  8.40),
    ("Graubuenden",           46.20, 47.10,   8.60, 10.60),
    ("Uri / Glarner Alpen",   46.65, 47.10,   8.40,  9.40),
    ("Mont-Blanc-Gruppe",     45.65, 46.05,   6.65,  7.20),
    ("Dauphine-Alpen",        44.80, 45.40,   5.50,  6.95),
    ("Cottische Alpen",       44.80, 45.50,   6.50,  7.40),
]


def country_from_lonlat(lat: float, lon: float) -> str:
    if lat > 47.3 and lon < 13.0:
        return "DE"
    if lat > 46.5 and lon < 9.6:
        return "CH"
    if lat < 46.5 and lon < 8.0:
        return "FR"
    if lat < 46.7 and lon >= 9.6:
        return "IT"
    return "AT"


def country_name(code: str) -> str:
    return COUNTRY_NAMES.get(code, code)


def region_from_lonlat(lat: float, lon: float) -> str:
    for name, s, n, w, e in REGIONS:
        if s <= lat <= n and w <= lon <= e:
            return name
    return "Alpen"
