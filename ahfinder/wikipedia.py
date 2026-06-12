"""Wikipedia-Lookup + Bilder (Summary API + MediaWiki Action API + Wikidata)."""
from __future__ import annotations

import json
import re
from typing import List, Optional
from urllib.parse import quote

from .cache import cache_get, cache_set
from .config import CONFIG, cache_key
from .http import http_get


def _candidate_transliteration(name: str) -> str:
    replacements = {
        "ae": "\u00e4", "oe": "\u00f6", "ue": "\u00fc",
        "Ae": "\u00c4", "Oe": "\u00d6", "Ue": "\u00dc", "ss": "\u00df",
    }
    out = re.sub(r"[äöüÄÖÜß]", "?", name)
    for k, v in replacements.items():
        out = out.replace(k, v)
    return out


# Die Schweiz hat vier Landessprachen - Huetten in der Romandie ("Cabane ...",
# "Refuge ...") oder im Tessin ("Capanna ...", "Rifugio ...") haben ihren
# Wikipedia-Artikel (inkl. Bild) meist nur auf fr./it.wikipedia.org, nicht auf
# der deutschen Wikipedia. Anhand typischer Namensbestandteile schaetzen wir
# die wahrscheinlichste Sprachversion und fragen sie zuerst ab.
_LANG_NAME_HINTS = [
    ("fr", ("cabane", "refuge", "chalet", "gite", "abri")),
    ("it", ("capanna", "rifugio", "bivacco", "baita", "casa")),
    ("de", ("hutte", "haus", "berghaus")),
]


def _guess_lang_order(name: str) -> List[str]:
    """Liefert eine nach Wahrscheinlichkeit sortierte Liste der drei
    Hauptsprachen (de/fr/it) fuer den Wikipedia-Lookup eines Huettennamens."""
    lname = name.lower().replace("ü", "u").replace("ä", "a").replace("ö", "o")
    for lang, keywords in _LANG_NAME_HINTS:
        if any(kw in lname for kw in keywords):
            return [lang] + [l for l in ("de", "fr", "it") if l != lang]
    return ["de", "fr", "it"]


def _is_definitive_miss(r: dict) -> bool:
    """True nur bei HTTP 404 - also wenn die Seite nachweislich nicht existiert.

    Timeouts, Netzwerkfehler oder 5xx-Antworten sind TRANSIENT und duerfen
    NICHT als "nicht gefunden" gecacht werden: Sonst "vergiftet" ein
    einmaliger, kurzer Ausfall (z.B. 5s-Timeout unter Last bei parallelen
    Anfragen) das Ergebnis fuer 24h, obwohl die Seite existiert. Genau das
    ist z.B. bei der Rottalhuette passiert - obwohl der OSM-Tag korrekt auf
    "de:Rottalhütte" zeigt und die Seite ein Bild hat, wurde der Lookup
    einmalig negativ gecacht und blieb dann einen Tag lang "verschollen".
    """
    return r.get("code") == 404


def _fetch_image_via_action_api(lang: str, title: str) -> Optional[str]:
    """Holt ein grosses Bild ueber die MediaWiki Action API."""
    ck = cache_key("wiki_img", lang, title)
    cached = cache_get(ck)
    if cached is not None:
        return cached or None

    endpoint = f"https://{lang}.wikipedia.org/w/api.php"
    url = (
        f"{endpoint}?action=query&titles={quote(title.replace(' ', '_'))}"
        f"&prop=pageimages&format=json&pithumbsize=600&origin=*"
    )
    r = http_get(url, 5)
    if r["code"] != 200 or not r["body"]:
        if _is_definitive_miss(r):
            cache_set(ck, False, 86400)
        return None
    try:
        j = json.loads(r["body"])
        pages = j.get("query", {}).get("pages", {})
        for pid, pdata in pages.items():
            thumb = pdata.get("thumbnail", {}).get("source")
            if thumb:
                cache_set(ck, thumb, 86400)
                return thumb
    except (json.JSONDecodeError, AttributeError):
        return None
    cache_set(ck, False, 86400)
    return None


def _search_wikidata_by_name(name: str) -> Optional[str]:
    """Sucht per Wikidata nach einem Item, das dem Namen aehnelt."""
    ck = cache_key("wikidata_search", name.lower().replace(" ", "_"))
    cached = cache_get(ck)
    if cached is not None:
        return cached if isinstance(cached, str) and cached.startswith("Q") else None

    url = (
        f"{CONFIG['wikidata']['endpoint']}?action=wbsearchentities"
        f"&search={quote(name)}&language=de&format=json&limit=1"
    )
    r = http_get(url, 5)
    if r["code"] != 200 or not r["body"]:
        if _is_definitive_miss(r):
            cache_set(ck, False, 86400)
        return None
    try:
        j = json.loads(r["body"])
        items = j.get("search", [])
        if items:
            qid = items[0].get("id")
            if qid and qid.startswith("Q"):
                cache_set(ck, qid, 86400)
                return qid
    except (json.JSONDecodeError, AttributeError):
        return None
    cache_set(ck, False, 86400)
    return None


def _fetch_wikidata_image(qid: str) -> Optional[str]:
    """Holt Bild ueber Wikidata P18 (Bild-Eigenschaft)."""
    if not qid:
        return None
    ck = cache_key("wikidata_img", qid)
    cached = cache_get(ck)
    if cached is not None:
        return cached or None

    url = (
        f"{CONFIG['wikidata']['endpoint']}?action=wbgetentities"
        f"&ids={quote(qid)}&props=claims&format=json"
    )
    r = http_get(url, 5)
    if r["code"] != 200 or not r["body"]:
        if _is_definitive_miss(r):
            cache_set(ck, False, 86400)
        return None
    try:
        j = json.loads(r["body"])
        claims = j.get("entities", {}).get(qid, {}).get("claims", {}).get("P18", [])
        if claims:
            filename = claims[0].get("mainsnak", {}).get("datavalue", {}).get("value")
            if filename:
                # Wikimedia Commons Thumbnail-URL
                safe = filename.replace(" ", "_")
                thumb_url = f"https://commons.wikimedia.org/wiki/Special:FilePath/{quote(safe)}?width=600"
                cache_set(ck, thumb_url, 86400)
                return thumb_url
    except (json.JSONDecodeError, AttributeError):
        return None
    cache_set(ck, False, 86400)
    return None


def fetch_wikipedia(h: dict) -> Optional[dict]:
    candidates: List[tuple] = []
    if h.get("wikipedia"):
        wp = h["wikipedia"]
        if ":" in wp:
            lang, title = wp.split(":", 1)
        else:
            lang, title = "de", wp
        candidates.append((lang, title))

    # Schweiz = vier Landessprachen: den Huettennamen in de/fr/it abfragen,
    # in der Reihenfolge die anhand des Namens am wahrscheinlichsten ist
    # (z.B. "Cabane ..." -> zuerst Franzoesisch, "Capanna ..." -> Italienisch).
    for lang in _guess_lang_order(h["name"]):
        candidates.append((lang, h["name"]))

    ascii_name = _candidate_transliteration(h["name"])
    if ascii_name != h["name"]:
        candidates.append(("en", ascii_name))

    tried: set = set()
    for lang, title in candidates:
        key2 = f"{lang}|{title}"
        if key2 in tried:
            continue
        tried.add(key2)

        ck = cache_key("wiki", lang, title)
        cached = cache_get(ck)
        if cached is not None:
            if cached is False:
                continue
            # Veraltete Eintraege ohne Bild aktualisieren
            if not cached.get("image"):
                big_img = _fetch_image_via_action_api(lang, title)
                if big_img:
                    cached["image"] = big_img
                    cache_set(ck, cached, 86400)
            return cached

        # de/en haben konfigurierte Endpoints, fr/it werden nach demselben
        # Schema dynamisch gebaut (https://{lang}.wikipedia.org/api/rest_v1).
        base = CONFIG["wikipedia"].get(f"{lang}_endpoint") or (
            f"https://{lang}.wikipedia.org/api/rest_v1"
        )
        url = f"{base}/page/summary/{quote(title.replace(' ', '_'))}"
        r = http_get(url, 5)
        if r["code"] != 200 or not r["body"]:
            # Nur bei HTTP 404 (Seite existiert nachweislich nicht) negativ
            # cachen - Timeouts/Netzwerkfehler/5xx sind transient und sollen
            # beim naechsten Suchlauf erneut versucht werden (siehe
            # _is_definitive_miss / Rottalhuette-Bug).
            if _is_definitive_miss(r):
                cache_set(ck, False, 86400)
            continue
        try:
            j = json.loads(r["body"])
        except json.JSONDecodeError:
            continue
        if not isinstance(j, dict) or j.get("type") == "disambiguation":
            cache_set(ck, False, 86400)
            continue

        # Summary-API Bild (meist klein), dann Action API fuer groesseres Bild
        image = (j.get("originalimage") or j.get("thumbnail") or {}).get("source")
        if not image:
            image = _fetch_image_via_action_api(lang, j.get("title") or title)
        # Falls nix gefunden, probiere Wikidata-Bild
        if not image and h.get("wikidata"):
            image = _fetch_wikidata_image(h["wikidata"])
        if not image:
            qid = _search_wikidata_by_name(h["name"])
            if qid:
                image = _fetch_wikidata_image(qid)

        out = {
            "lang": lang,
            "title": j.get("title") or title,
            "url": (j.get("content_urls") or {}).get("desktop", {}).get("page"),
            "image": image,
            "extract": j.get("extract"),
        }
        cache_set(ck, out, 86400)
        return out

    return None
