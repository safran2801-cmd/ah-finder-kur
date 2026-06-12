"""SAC-Tourenportal: saisonale Bewartungs-/Öffnungsinfos pro Hütte.

Liefert ein kompaktes, LLM-lesbares Faktum wie "bewartet: Mai-Oktober" durch
Scraping der öffentlich zugänglichen "Zusatzinformationen" auf der
SAC-Tourenportal-Detailseite (statisches HTML, ohne JavaScript abrufbar).

WICHTIG - Abgrenzung zu "echter" Verfügbarkeit:
Dies ist NICHT die tagesgenaue Bettenverfügbarkeit für eine Reservation
("an welchen Tagen sind noch Betten frei"). Diese Information liegt auf der
separaten Buchungsplattform hut-reservation.org, einer JavaScript-Single-
Page-App, deren interne Daten-API nicht öffentlich dokumentiert ist und ohne
Browser-Netzwerkanalyse nicht zuverlässig ansteuerbar ist.

Was hier geliefert wird, ist die saisonale "ist die Hütte aktuell überhaupt
bewartet"-Information (z.B. "Hütte bewartet: Mai-Oktober", "Schutzraum das
ganze Jahr offen"), die der SAC selbst auf jeder Hüttenseite veröffentlicht -
nützlich um z.B. zu beantworten "ist die Hütte im Winter offen?" / "wann ist
die Hütte bewartet?".
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional
from urllib.parse import quote, unquote, urlparse

from .cache import cache_get, cache_set
from .config import CONFIG, cache_key
from .http import http_get

_MONTHS = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]
_MONTH_NAMES = {
    "Jan": "Januar", "Feb": "Februar", "Mär": "März", "Apr": "April",
    "Mai": "Mai", "Jun": "Juni", "Jul": "Juli", "Aug": "August",
    "Sep": "September", "Okt": "Oktober", "Nov": "November", "Dez": "Dezember",
}


def _strip_html(body: str) -> str:
    """Wandelt HTML in normalisierten Klartext um."""
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", body)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;|&#160;", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _load_sac_mapping() -> dict:
    """Lädt die statische Zuordnung Hüttenname -> SAC-Portal-URL aus JSON."""
    mapping_path = Path(__file__).parent / "sac_hut_mapping.json"
    if not mapping_path.exists():
        return {}
    try:
        with open(mapping_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


_SAC_MAPPING = None


def _get_sac_mapping() -> dict:
    """Gibt die gecachte SAC-Hütten-Zuordnung zurück."""
    global _SAC_MAPPING
    if _SAC_MAPPING is None:
        _SAC_MAPPING = _load_sac_mapping()
    return _SAC_MAPPING


def _names_similar(name1: str, name2: str) -> bool:
    """Prüft ob zwei Hüttennamen ähnlich genug sind."""
    n1 = name1.lower().replace("ä", "a").replace("ö", "o").replace("ü", "u").replace(" ", "")
    n2 = name2.lower().replace("ä", "a").replace("ö", "o").replace("ü", "u").replace(" ", "")

    if n1 == n2:
        return True
    short_name, long_name = (n1, n2) if len(n1) <= len(n2) else (n2, n1)
    if len(short_name) >= 8 and short_name in long_name:
        return True
    if len(n1) > 10 and len(n2) > 10:
        common_len = min(len(n1), len(n2))
        return n1[:common_len] == n2[:common_len]
    return False


def _find_tourenportal_url(hut_name: str) -> Optional[str]:
    """Findet die SAC-Tourenportal-Detailseite einer Hütte."""
    mapping = _get_sac_mapping()
    clean_name = hut_name.strip()

    if clean_name in mapping:
        return mapping[clean_name]

    for map_name, map_url in mapping.items():
        if _names_similar(clean_name, map_name):
            return map_url

    ck = cache_key("sac_portal_url_v2", hut_name.lower().strip())
    cached = cache_get(ck)
    if cached is not None:
        return cached or None

    q = quote(f"{hut_name} site:sac-cas.ch sac-tourenportal")
    url = f"{CONFIG['duckduckgo']['endpoint']}?q={q}"
    r = http_get(url, 8)
    if r["code"] != 200 or not r["body"]:
        cache_set(ck, False, CONFIG["cache"]["huetten_ttl"])
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


_SAC_BLOCKED_HOSTS = (
    "sac-cas.ch",
    "sac-cas-shop.ch",
    "facebook.com",
    "instagram.com",
    "youtube.com",
    "twitter.com",
    "x.com",
    "maps.google.",
    "google.com",
    "goo.gl",
)


def _score_external_hut_website(url: str) -> int:
    """Bewertet externe Links von der SAC-Detailseite."""
    u = (url or "").strip()
    if not re.match(r"^https?://", u, re.IGNORECASE):
        return -1

    parsed = urlparse(u)
    host = (parsed.hostname or "").lower()
    full = u.lower()

    if not host:
        return -1
    if any(blocked in full or blocked in host for blocked in _SAC_BLOCKED_HOSTS):
        return -1

    if any(token in host for token in ("hut-reservation", "alpsonline", "mountain-booking")):
        return 10
    if any(token in full for token in ("reservation", "reservierung", "booking", "buchen")):
        return 20

    return 100


def _extract_best_external_url_from_html(html: str) -> Optional[str]:
    """Extrahiert bevorzugt die offizielle Hütten-Homepage aus dem Online-Bereich."""
    if not html:
        return None

    candidates: list[tuple[int, str]] = []
    section_patterns = [
        (
            r"Online(.*?)(?:Dienstleistungen|H[üu]ttenwart|H[üu]ttenchef|Eigent[üu]mer|"
            r"Partnerangebote|Mehr Weniger|R[üu]ckmeldung)"
        ),
        (r"Online(.*?)(?:</section>|</ul>|</div>)"),
    ]

    for pattern in section_patterns:
        match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if not match:
            continue
        chunk = match.group(1)
        for href in re.findall(r'href=["\']([^"\']+)["\']', chunk, re.IGNORECASE):
            score = _score_external_hut_website(href)
            if score >= 0:
                candidates.append((score, href))
        if candidates:
            break

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def find_sac_official_website(hut_name: str, portal_url: Optional[str] = None) -> Optional[str]:
    """Liest die offizielle Hütten-Website direkt aus der SAC-Detailseite aus."""
    ck = cache_key("sac_official_site", hut_name.lower().strip())
    cached = cache_get(ck)
    if cached is not None:
        return cached or None

    url = portal_url or _find_tourenportal_url(hut_name)
    if not url:
        cache_set(ck, False, CONFIG["cache"]["huetten_ttl"])
        return None

    r = http_get(url, 10)
    if r["code"] != 200 or not r["body"]:
        return None

    website = _extract_best_external_url_from_html(r["body"])
    cache_set(ck, website if website else False, CONFIG["cache"]["huetten_ttl"])
    return website


def find_sac_hut_id(hut_name: str) -> Optional[int]:
    """Extrahiert die SAC-Hütten-ID aus der Tourenportal-URL."""
    ck = cache_key("sac_hut_id", hut_name.lower().strip())
    cached = cache_get(ck)
    if cached is not None:
        return cached or None

    portal_url = _find_tourenportal_url(hut_name)
    if not portal_url:
        cache_set(ck, False, CONFIG["cache"]["huetten_ttl"])
        return None

    match = re.search(r"-(\d+)/?$", portal_url)
    if match:
        hut_id = int(match.group(1))
        cache_set(ck, hut_id, CONFIG["cache"]["huetten_ttl"])
        return hut_id

    cache_set(ck, False, CONFIG["cache"]["huetten_ttl"])
    return None


def _extract_month_status(text: str, label_pattern: str) -> Optional[dict]:
    """Extrahiert Monat->Status-Paare aus dem Abschnitt nach dem Label."""
    m = re.search(
        label_pattern + r"(.{0,400}?)"
        r"(?=H[üu]ttentelefon|Kapazit[äa]t|Online|Dienstleistungen|H[üu]ttenwart|"
        r"H[üu]ttenchef|Eigent[üu]mer|$)",
        text, re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return None
    chunk = m.group(1)
    result = {}
    for mon in _MONTHS:
        mm = re.search(re.escape(mon) + r"\s*:?\s*(Offen|Geschlossen)", chunk, re.IGNORECASE)
        if mm:
            result[mon] = mm.group(1).capitalize()
    return result or None


def _summarize_open_months(status: dict) -> Optional[str]:
    """Fasst zusammenhängende offene Monate kompakt zusammen."""
    open_set = {i for i, mon in enumerate(_MONTHS) if status.get(mon) == "Offen"}
    if not open_set:
        return "ganzjährig geschlossen"
    if len(open_set) == 12:
        return "ganzjährig geöffnet"

    starts = sorted(i for i in open_set if (i - 1) % 12 not in open_set)
    parts = []
    for s in starts:
        e = s
        while (e + 1) % 12 in open_set:
            e = (e + 1) % 12
        if s == e:
            parts.append(_MONTH_NAMES[_MONTHS[s]])
        else:
            parts.append(f"{_MONTH_NAMES[_MONTHS[s]]}–{_MONTH_NAMES[_MONTHS[e]]}")
    return ", ".join(parts)


def fetch_sac_season_info(hut_name: str) -> Optional[dict]:
    """Liefert saisonale Bewartungsinfos einer SAC-Hütte."""
    ck = cache_key("sac_season", hut_name.lower().strip())
    cached = cache_get(ck)
    if cached is not None:
        return cached or None

    url = _find_tourenportal_url(hut_name)
    if not url:
        return None

    r = http_get(url, 10)
    if r["code"] != 200 or not r["body"]:
        return None

    text = _strip_html(r["body"])
    bewartet = _extract_month_status(text, r"H[üu]tte\s+bewartet")
    schutzraum = _extract_month_status(text, r"Schutzraum\s+offen")

    if not bewartet and not schutzraum:
        cache_set(ck, False, CONFIG["cache"]["huetten_ttl"])
        return None

    out = {
        "url": url,
        "bewartet": bewartet,
        "bewartet_text": _summarize_open_months(bewartet) if bewartet else None,
        "schutzraum": schutzraum,
        "schutzraum_text": _summarize_open_months(schutzraum) if schutzraum else None,
    }
    cache_set(ck, out, CONFIG["cache"]["huetten_ttl"])
    return out
