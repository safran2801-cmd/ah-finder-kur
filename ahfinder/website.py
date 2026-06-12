"""Suche nach der offiziellen Website (OSM-Tag -> Wikidata P856 -> DuckDuckGo)."""
from __future__ import annotations

import json
import re
from typing import Optional
from urllib.parse import parse_qs, quote, unquote, urlparse

from .cache import cache_get, cache_set
from .config import CONFIG, cache_key
from .http import http_get


BLOCKED_DOMAINS = [
    "wikipedia.org", "wikidata.org", "osm.org", "openstreetmap.org",
    "hut-reservation.org", "booking.com", "tripadvisor.com",
    "facebook.com", "instagram.com", "twitter.com", "youtube.com", "google.com",
]


# Bekannte offizielle Websites fuer oft gesuchte Huetten (spart DuckDuckGo-Requests)
KNOWN_SITES: dict = {
    "tegernseer huette": "https://www.tegernseer-huette.de",
    "hoellentalangerhuette": "https://www.hoellental-angerhuette.de",
    "watzmannhaus": "https://www.watzmannhaus.de",
    "rappenseehuette": "https://www.rappenseehuette.de",
    "kemptner huette": "https://www.kemptner-huette.de",
    "muenchner haus": "https://www.muetnchner-haus.de",
    "knorrhuette": "https://www.knorrhuette.de",
    "blaueishuette": "https://www.blaueishuette.de",
    "staufner haus": "https://www.staufner-haus.de",
    "mittenwalder huette": "https://www.mittenwalder-huette.de",
    "soiernhaus": "https://www.soiernhaus.de",
    "meilerhuette": "https://www.meilerhuette.de",
    "brandenburger huette": "https://www.brandenburger-huette.at",
    "heinrich-schwaiger-haus": "https://www.schwaigerhaus.at",
    "kuersinger huette": "https://www.kuersingerhuette.at",
    "neue prager huette": "https://www.pragerhuette.at",
    "simonyhuette": "https://www.dachstein-salzkammergut.at",
    "hofpuerglhuette": "https://www.hofpuerglhuette.at",
    "adameqhuette": "https://www.adamekhuette.at",
    "wolayerseehuette": "https://www.wolayerseehuette.at",
    "elberfelder huette": "https://www.elberfelderhuette.at",
    "defreggerhaus": "https://www.defreggerhaus.at",
    "sudetendeutsche huette": "https://www.sudetenhuette.at",
    "gaulihuette": "https://www.gaulihuette.ch",
    "schreckhornhuette": "https://www.schreckhornhuette.ch",
    "finsteraarhornhuette": "https://www.finsteraarhornhuette.ch",
    "glecksteinhuette": "https://www.glecksteinhuette.ch",
    "dossenhuette": "https://www.dossenhuette.ch",
    "trifthuette": "https://www.trifthuette.ch",
    "rifugio locatelli": "https://www.rifugiolocatelli.it",
    "rifugio lagazuoi": "https://www.rifugiolagazuoi.com",
    "rifugio vajolet": "https://www.rifugiovajolet.it",
    "rifugio bolzano": "https://www.rifugiobolzano.com",
    "rifugio auronzo": "https://www.rifugioauronzo.it",
    "rifugio brentei": "https://www.rifugiobrentei.it",
    "rifugio tuckett": "https://www.rifugiotuckett.it",
    "refuge du gouter": "https://www.refugedugouter.fr",
    "refuge des cosmiques": "https://www.refugecosmiques.com",
    "refuge de la pilatte": "https://www.refugedelapilatte.fr",
    "refuge du promontoire": "https://www.refugedupromontoire.fr",
    "refuge de l'aigle": "https://www.refugedelaigle.fr",
}


def _web_search_official_site(hut_name: str) -> Optional[str]:
    # Bessere Suchanfrage für Schweizer Hütten
    q = quote(f"{hut_name} SAC Hütte offizielle Website Schweiz")
    url = f"{CONFIG['duckduckgo']['endpoint']}?q={q}&kl=ch-de"
    r = http_get(url, 8)
    if r["code"] != 200 or not r["body"]:
        return None

    candidates: list[tuple[int, str]] = []
    name_words = [w.lower() for w in re.split(r"\W+", hut_name) if len(w) > 3]

    for enc in re.findall(r'uddg=([^"&]+)', r["body"]):
        u = unquote(enc)
        if not re.match(r"^https?://", u, re.IGNORECASE):
            continue
        parsed = urlparse(u)
        host = (parsed.hostname or "").lower()
        if any(b in host for b in BLOCKED_DOMAINS):
            continue
        # Score: bevorzuge URLs die den Hüttennamen enthalten
        full = (host + parsed.path).lower()
        score = sum(1 for w in name_words if w in full)
        candidates.append((score, u))

    # Beste URL zuerst prüfen (nach Score absteigend)
    for _, u in sorted(candidates, key=lambda x: x[0], reverse=True):
        check = http_get(u, 6)
        if check["code"] == 200:
            return u

    return None


def _is_definitive_miss(r: dict) -> bool:
    """True nur bei HTTP 404 (Eintrag existiert nachweislich nicht).

    Timeouts/Netzwerkfehler/5xx sind transient und sollen NICHT lange negativ
    gecacht werden - sonst "vergiftet" ein einmaliger Ausfall das Ergebnis
    fuer 24h, obwohl ein erneuter Versuch erfolgreich waere (siehe selbes
    Problem in wikipedia.py, das z.B. die Rottalhuette betraf).
    """
    return r.get("code") == 404


def _wikidata_website(qid: str) -> Optional[str]:
    ck = cache_key("wikidata_website", qid)
    cached = cache_get(ck)
    if cached is not None:
        return cached or None

    url = (
        f"{CONFIG['wikidata']['endpoint']}?action=wbgetentities"
        f"&ids={quote(qid)}&props=claims&format=json"
    )
    r = http_get(url, CONFIG["wikidata"]["timeout"])
    if r["code"] != 200 or not r["body"]:
        if _is_definitive_miss(r):
            cache_set(ck, False, CONFIG["cache"]["huetten_ttl"])
        return None
    try:
        j = json.loads(r["body"])
    except json.JSONDecodeError:
        return None

    claims = (
        (j.get("entities") or {})
        .get(qid, {})
        .get("claims", {})
        .get("P856")
    )
    site = None
    if isinstance(claims, list) and claims:
        val = claims[0].get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(val, str):
            site = val if re.match(r"^https?://", val, re.IGNORECASE) else "https://" + val.lstrip("/")

    cache_set(ck, site, CONFIG["cache"]["huetten_ttl"])
    return site


def find_official_website(h: dict) -> Optional[str]:
    site = h.get("website")
    if site and re.match(r"^https?://", site, re.IGNORECASE):
        return site

    qid = (h.get("wikidata") or "").strip()
    if re.match(r"^Q\d+$", qid):
        wd = _wikidata_website(qid)
        if wd:
            return wd

    # Schneller Lookup fuer bekannte Huetten (vermeidet langsame DuckDuckGo-Suche)
    name_key = h["name"].lower().strip()
    if name_key in KNOWN_SITES:
        return KNOWN_SITES[name_key]

    ck = cache_key("websearch_site", h["name"].lower())
    cached = cache_get(ck)
    if cached is not None:
        return cached or None
    found = _web_search_official_site(h["name"])
    cache_set(ck, found, CONFIG["cache"]["huetten_ttl"])
    return found
