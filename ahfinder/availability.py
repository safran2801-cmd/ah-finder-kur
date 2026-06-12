"""SAC-Tourenportal: tagesgenaue Bettenverfügbarkeit der nächsten Wochen.

Extrahiert die öffentlich sichtbare Verfügbarkeitscalender aus der
Reservierungskomponente auf der SAC-Tourenportal-Hüttendetailseite:
- Grüne Punkte = "reservation-possible" (Betten frei)
- Rote Punkte = "reservation-not-possible" (ausgebucht)

Die Daten werden direkt aus dem gerenderten HTML gescraped, nicht aus der
internen huts-middleware-API, da diese nicht öffentlich dokumentiert ist.

Liefert ein Dict wie:
{
  "2026-06-08": "available",
  "2026-06-09": "available",
  "2026-06-13": "booked",
  ...
}

Oder None wenn die Seite nicht abrufbar ist oder die Hütte kein Reservierungssystem nutzt.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote, unquote

from .cache import cache_get, cache_set
from .config import CONFIG, cache_key
from .http import http_get


def _find_tourenportal_url(hut_name: str) -> Optional[str]:
    """Findet die SAC-Tourenportal-Detailseite einer Hütte per DuckDuckGo-Suche."""
    ck = cache_key("sac_portal_url", hut_name.lower().strip())
    cached = cache_get(ck)
    if cached is not None:
        return cached or None

    q = quote(f"{hut_name} site:sac-cas.ch sac-tourenportal")
    url = f"{CONFIG['duckduckgo']['endpoint']}?q={q}"
    r = http_get(url, 8)
    if r["code"] != 200 or not r["body"]:
        return None

    found = None
    for enc in re.findall(r'uddg=([^"&]+)', r["body"]):
        u = unquote(enc)
        if (
            re.match(r"^https?://(www\.)?sac-cas\.ch/de/huetten-und-touren/sac-tourenportal/", u)
            and re.search(r"-\d+/?($|[?#])", u)
        ):
            found = u.split("?")[0].rstrip("/") + "/"
            break

    cache_set(ck, found if found else False, CONFIG["cache"]["huetten_ttl"])
    return found


def _parse_availability_html(html: str) -> Optional[dict]:
    """Extrahiert die Verfügbarkeitscalender-Daten aus dem Reservierungswidget-HTML.

    Sucht nach HTML wie:
      <li class="m-hut-reservation__date m-hut-reservation__date--reservation-possible">
        <a ...>Mo 08.06.26</a>
      </li>
    oder
      <li class="m-hut-reservation__date m-hut-reservation__date--reservation-not-possible">
        So 14.06.26 (kein Link)
      </li>
    """
    # Extrahiere alle <li class="m-hut-reservation__date ...">-Elemente direkt
    availability = {}
    date_pattern = r'<li[^>]*class="[^"]*m-hut-reservation__date([^"]*)"[^>]*>(.*?)</li>'

    for li_match in re.finditer(date_pattern, html, re.DOTALL):
        class_str = li_match.group(1)
        li_content = li_match.group(2)

        # Bestimme Status aus der Klasse
        if "reservation-possible" in class_str and "not-possible" not in class_str:
            status = "available"
        elif "reservation-not-possible" in class_str:
            status = "booked"
        else:
            continue

        # Extrahiere das Datum (z.B. "Mo 08.06.26", "Di 09.06.26")
        date_match = re.search(
            r'(?:Mo|Di|Mi|Do|Fr|Sa|So)\s+(\d{2}\.\d{2}\.\d{2})',
            li_content
        )
        if date_match:
            date_str = date_match.group(1)  # Format: "08.06.26"
            # Konvertiere zu ISO-Format YYYY-MM-DD
            try:
                d = datetime.strptime(date_str, "%d.%m.%y").date()
                iso_date = d.isoformat()
                availability[iso_date] = status
            except ValueError:
                pass

    return availability if availability else None


def fetch_hut_availability(hut_name: str, poi_id: Optional[int] = None) -> Optional[dict]:
    """Holt die tagesgenaue Verfügbarkeit einer SAC-Hütte (nächste ~20 Tage).

    Liefert ein Dict wie {"2026-06-08": "available", "2026-06-13": "booked", ...}
    oder None wenn die Hütte nicht im Tourenportal gelistet ist oder kein
    Reservierungssystem hat.

    Falls poi_id gegeben ist, wird die URL direkt konstruiert (schneller).
    Sonst wird die URL via DuckDuckGo gesucht.
    """
    ck = cache_key("hut_availability", hut_name.lower().strip())
    cached = cache_get(ck)
    if cached is not None:
        return cached or None

    # Finde Tourenportal-URL
    portal_url = None

    if poi_id:
        # Direkt URL konstruieren mit bekannter POI-ID (schneller)
        slug = hut_name.lower().replace(" ", "").replace("ü", "ue").replace("ä", "ae").replace("ö", "oe")
        portal_url = f"https://www.sac-cas.ch/de/huetten-und-touren/sac-tourenportal/{slug}-{poi_id}/"
    else:
        # Fallback 1: Slug-basierte URL versuchen (ohne POI-ID)
        # Manche URLs funktionieren mit Slug allein
        slug = hut_name.lower().replace(" ", "-").replace("ü", "ue").replace("ä", "ae").replace("ö", "oe")
        test_url = f"https://www.sac-cas.ch/de/huetten-und-touren/sac-tourenportal/{slug}/"
        r_test = http_get(test_url, timeout=5)
        if r_test["code"] == 200 and r_test["body"]:
            portal_url = test_url
        else:
            # Fallback 2: URL via DuckDuckGo suchen
            portal_url = _find_tourenportal_url(hut_name)

    if not portal_url:
        cache_set(ck, False, CONFIG["cache"]["huetten_ttl"])
        return None

    # Hole die Seite
    r = http_get(portal_url, timeout=10)
    if r["code"] != 200 or not r["body"]:
        # Transient error - nicht negativ cachen
        return None

    # Parse Verfügbarkeit
    availability = _parse_availability_html(r["body"])

    # Cache mit kürzerer TTL als normale Hütteninfo (da Verfügbarkeit sich täglich ändert)
    # Setze 6 Stunden als TTL
    cache_ttl = 6 * 3600
    cache_set(ck, availability if availability else False, cache_ttl)

    return availability


if __name__ == "__main__":
    # Test
    result = fetch_hut_availability("Treschhütte SAC")
    print(result)
