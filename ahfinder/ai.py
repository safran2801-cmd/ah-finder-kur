"""OpenAI-Empfehlung mit identischem Prompt wie die PHP-Version."""
from __future__ import annotations

import json
import re
from typing import Optional

from .cache import cache_get, cache_set
from .config import (
    API_ENDPOINT,
    CONFIG,
    INFOMANIAK_API_KEY,
    MODEL_NAME,
    cache_key,
)
from .geo import country_name, region_from_lonlat
from .http import http_post


CHAT_SYSTEM_PROMPT = (
    "Du bist ein kompetenter Assistent für den Schweizer Hütten-Finder. "
    "Dir werden Daten zu den aktuell gefundenen Berghütten übergeben. "
    "Beantworte Fragen des Benutzers zu diesen Hütten ausführlich, sachlich und präzise auf Deutsch. "
    "Nutze IMMER zuerst die dir übergebenen Hüttendaten als Grundlage. "
    "Falls eine Information darin fehlt, MUSST du aktiv die verfügbaren Werkzeuge nutzen – "
    "sage NIEMALS einfach, dass du es nicht weisst. Werkzeuge in der richtigen Reihenfolge: "
    "1. check_hut_availability: Bei JEDER Frage nach Verfügbarkeit, freien Plätzen, ob man "
    "reservieren kann, ob die Hütte frei/ausgebucht ist – rufe SOFORT dieses Tool auf. "
    "Verweise den Nutzer NICHT auf externe Links, sondern liefere die konkreten Daten direkt. "
    "2. fetch_hut_website: Für Kontakt, E-Mail, Telefon, Preise, Anreise. "
    "3. search_wikipedia: Für Geschichte, Geografie, alpine Hintergründe. "
    "4. search_web: Für aktuelle Infos wie Neuigkeiten. "
    "Nutze so viele Werkzeuge wie nötig, auch mehrere nacheinander, um eine vollständige Antwort zu liefern. "
    "Antworte dann ausführlich und hilfreich. Kein Markdown, keine Sternchen, kein Fettdruck. "
    "WICHTIG: Wiederhole bei Folgefragen KEINE bereits genannten Informationen. "
    "Beantworte nur das Neue, was der Nutzer gerade fragt."
)

SYSTEM_PROMPT = (
    "Du bist ein erfahrener Alpenwanderer und Wetterexperte. "
    "Du schreibst kompakte, sachliche Empfehlungen auf Deutsch. "
    "Maximal 3 Sätze, maximal 70 Wörter. "
    "Keine Aufzählungen, keine Überschriften, KEINE URLs, "
    "keine erfundenen Fakten. Stütze dich ausschliesslich auf die gelieferten Daten. "
    "WICHTIG: Kein Markdown. Keine Sternchen, kein Fettdruck, keine Unterstriche, "
    "kein Kursivdruck. Nur einfacher Fliesstext."
)


def _is_placeholder_key(api_key: str) -> bool:
    if not api_key:
        return True
    if "PLACEHOLDER" in api_key.upper():
        return True
    return False


def _static_fallback(h: dict, weather: dict, wiki: Optional[dict],
                     sat_label: str, sun_label: str) -> str:
    s = weather["sat"]
    u = weather["sun"]
    region = h.get("__region") or region_from_lonlat(float(h["lat"]), float(h["lon"]))
    country = country_name(h["country"])
    extract = (wiki or {}).get("extract") or ""
    if len(extract) > 220:
        extract = extract[:220] + "..."

    parts = [
        (
            f"Huette {h['name']} ({h.get('ele') or 0} m) in der Region {region} ({country}): "
            f"{s['weatherText']} am Samstag mit bis {s['tempMax']:.0f} Grad "
            f"und {s['sunshineHours']:.1f} Sonnenstunden, "
            f"{u['weatherText']} am Sonntag mit bis {u['tempMax']:.0f} Grad "
            f"und {u['sunshineHours']:.1f} Sonnenstunden."
        ),
        (
            f"Niederschlag {s['precipitation']:.1f} mm / {u['precipitation']:.1f} mm, "
            f"Schnee {s['snowfall']:.1f} cm / {u['snowfall']:.1f} cm - "
            f"Wetter-Score {weather['total']} Punkte."
        ),
    ]
    if extract:
        parts.append(extract)
    return " ".join(parts)


def build_recommendation(h: dict, weather: dict, wiki: Optional[dict],
                         sat_label: str, sun_label: str) -> str:
    ck = cache_key("ki", h["osm_id"], sat_label, sun_label, weather["total"])
    cached = cache_get(ck)
    if isinstance(cached, str) and cached:
        return cached

    api_key = INFOMANIAK_API_KEY
    info = _static_fallback(h, weather, wiki, sat_label, sun_label)

    if _is_placeholder_key(api_key):
        info += "\n\n(Hinweis: API-Key fehlt - Empfehlung wurde lokal generiert.)"
        return info

    payload = {
        "model": MODEL_NAME,
        "temperature": 0.7,
        "max_tokens": 220,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": info},
        ],
    }
    r = http_post(
        API_ENDPOINT,
        payload,
        timeout=10,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    if r["code"] == 200 and r["body"]:
        try:
            j = json.loads(r["body"])
            text = (j.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        except json.JSONDecodeError:
            text = ""
        text = re.sub(r"\s+", " ", text).strip()
        # Markdown-Formatierung entfernen, die kleine Modelle trotz Anweisung ausgeben
        text = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", text)
        text = re.sub(r"_{1,2}([^_]+)_{1,2}", r"\1", text)
        if text:
            cache_set(ck, text, CONFIG["cache"]["ki_ttl"])
            return text

    # Bei Timeout / Fehler sofort lokale Empfehlung
    info += "\n\n(Hinweis: KI-API langsam – lokale Empfehlung wurde generiert.)"
    return _static_fallback(h, weather, wiki, sat_label, sun_label)


CHAT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "check_hut_availability",
            "description": (
                "Prüft die aktuelle Bettenverfügbarkeit einer SAC-Hütte für die nächsten 14 Tage. "
                "Verwende dieses Tool wenn der Nutzer fragt ob eine Hütte frei ist, "
                "Betten verfügbar sind, ob man reservieren kann, oder ähnliche Verfügbarkeitsfragen. "
                "Gibt für jeden Tag an ob Betten frei (available) oder ausgebucht (booked) sind "
                "sowie die Anzahl freier Plätze."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "hut_name": {
                        "type": "string",
                        "description": "Name der Hütte, z.B. 'Gruebenhütte AACBs' oder 'Schönbielhütte'",
                    }
                },
                "required": ["hut_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_wikipedia",
            "description": (
                "Sucht auf Wikipedia nach Informationen zu einer Berghütte oder einem alpinen Begriff. "
                "Verwende dieses Tool wenn die gesuchte Info nicht in den Suchergebnissen vorhanden ist "
                "oder der Nutzer nach einer anderen Hütte fragt."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Suchbegriff, z.B. 'Schönbielhütte' oder 'Cabane du Mont Fort'",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": (
                "Sucht im Web nach Informationen wenn Wikipedia nichts Passendes liefert. "
                "Geeignet für aktuelle Infos wie Öffnungszeiten, Reservierungen oder Preise."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Suchbegriff",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_hut_website",
            "description": (
                "Ruft die offizielle Website einer Hütte direkt ab und extrahiert Kontaktinfos "
                "wie E-Mail-Adressen, Telefonnummern und Öffnungszeiten. "
                "Verwende dieses Tool ZUERST wenn der Nutzer nach E-Mail, Kontakt, Reservation, "
                "Telefon oder Buchung fragt – BEVOR du search_web verwendest. "
                "Nutze die 'Offizielle Website'-URL aus den Hüttendaten."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Die URL der offiziellen Hütten-Website",
                    }
                },
                "required": ["url"],
            },
        },
    },
]


def _tool_check_availability(hut_name: str) -> str:
    """Verfügbarkeit einer SAC-Hütte für die nächsten 14 Tage abfragen."""
    from .availability import fetch_hut_availability, find_portal_url
    from datetime import date

    portal_url = find_portal_url(hut_name)
    if not portal_url:
        return (
            f"Die Hütte '{hut_name}' wurde nicht im SAC-Hütten-Verzeichnis gefunden. "
            "Keine Verfügbarkeitsdaten verfügbar."
        )

    avail = fetch_hut_availability(hut_name)
    if not avail:
        return (
            f"Für '{hut_name}' sind keine Verfügbarkeitsdaten verfügbar "
            "(kein Online-Reservierungssystem oder Hütte nicht erreichbar)."
        )

    today = date.today()
    lines = [f"Verfügbarkeit '{hut_name}' (nächste 14 Tage):"]
    for iso_date, info in sorted(avail.items()):
        try:
            d = date.fromisoformat(iso_date)
        except ValueError:
            continue
        if d < today:
            continue
        weekday = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"][d.weekday()]
        status_label = "frei" if info["status"] == "available" else "ausgebucht"
        places = info["freePlaces"]
        places_str = f", {places} Plätze frei" if info["status"] == "available" and places > 0 else ""
        lines.append(f"  {weekday} {d.strftime('%d.%m.%Y')}: {status_label}{places_str}")

    return "\n".join(lines)


def _tool_wikipedia(query: str) -> str:
    """Wikipedia-Suche für den Chatbot.

    Zwei Probleme der alten Version behoben:
    1. Die Anfrage wurde direkt als Artikel-TITEL verwendet. Nutzer tippen aber
       oft Zusaetze wie "SAC"/"CAS", die nicht Teil des Titels sind
       (z.B. "Treschhütte SAC" -> der Artikel heisst nur "Treschhütte"),
       wodurch der Lookup faelschlich leer blieb. Jetzt wird zuerst die
       Wikipedia-Volltextsuche (de/fr/it) genutzt, um den echten Titel zu
       finden.
    2. Es wurde nur die kurze Einleitung (Summary-Extract) zurueckgegeben.
       Praktische Fragen wie "Anfahrt"/"Zugang" werden im Wikipedia-Artikel
       aber meist in eigenen Abschnitten beantwortet, die in der Einleitung
       gar nicht vorkommen. Jetzt wird der volle Artikeltext geholt und - wenn
       ein Begriff aus der Frage als Abschnittsueberschrift vorkommt (z.B.
       "Anfahrt", "Zugang", "Geschichte") - genau dieser Abschnitt geliefert.
    """
    from urllib.parse import quote
    from .http import http_get
    ck = cache_key("chat_wiki", query.lower().strip())
    cached = cache_get(ck)
    if cached:
        return cached

    qlower = query.lower()
    qwords = [w for w in re.findall(r"[a-zäöüß]+", qlower) if len(w) > 3]

    # Echten Artikeltitel per Volltextsuche ermitteln (robust ggü. Zusaetzen
    # wie "SAC"), dazu die Roh-Anfrage als Fallback in de/en mitnehmen.
    titles: list = []
    for lang in ("de", "fr", "it"):
        search_url = (
            f"https://{lang}.wikipedia.org/w/api.php?action=query&list=search"
            f"&srsearch={quote(query)}&format=json&srlimit=1&origin=*"
        )
        r = http_get(search_url, 6)
        if r["code"] == 200 and r["body"]:
            try:
                hits = json.loads(r["body"]).get("query", {}).get("search", [])
                if hits and hits[0].get("title"):
                    titles.append((lang, hits[0]["title"]))
            except json.JSONDecodeError:
                pass
    titles += [("de", query), ("en", query)]

    tried: set = set()
    for lang, title in titles:
        tk = (lang, title.lower())
        if tk in tried:
            continue
        tried.add(tk)

        extract_url = (
            f"https://{lang}.wikipedia.org/w/api.php?action=query&prop=extracts"
            f"&explaintext=1&titles={quote(title)}&format=json&origin=*"
        )
        r = http_get(extract_url, 8)
        if r["code"] != 200 or not r["body"]:
            continue
        try:
            pages = json.loads(r["body"]).get("query", {}).get("pages", {})
        except json.JSONDecodeError:
            continue

        for pdata in pages.values():
            text = (pdata.get("extract") or "").strip()
            if len(text) <= 50:
                continue

            # Volltext ist in "Einleitung" + "== Ueberschrift ==" Abschnitte
            # gegliedert. Passt ein Wort aus der Nutzerfrage zu einer
            # Ueberschrift (z.B. Frage "Anfahrt" <-> Abschnitt "Anfahrt"),
            # liefere genau diesen Abschnitt statt der Einleitung.
            parts = re.split(r"\n=+\s*([^=\n]+?)\s*=+\n", text)
            result = parts[0].strip()
            for i in range(1, len(parts) - 1, 2):
                heading = parts[i].strip().lower()
                if heading in qlower or any(w in heading for w in qwords):
                    result = f"{parts[i].strip()}: {parts[i + 1].strip()}"
                    break

            result = result[:700]
            cache_set(ck, result, 3600)
            return result

    return "Keine Wikipedia-Informationen gefunden."


def _tool_fetch_website(url: str) -> str:
    """Ruft eine Website direkt ab und extrahiert Kontaktinfos und Text.

    Erkennt auch Joomla-obfuskierte E-Mail-Adressen (JavaScript-Spam-Schutz),
    die bei normaler Textextraktion als Platzhalter erscheinen würden.
    """
    import html as _html
    from .http import http_get

    if not re.match(r"^https?://", url, re.IGNORECASE):
        return "Ungültige URL."

    ck = cache_key("fetch_website", url)
    cached = cache_get(ck)
    if cached:
        return cached

    r = http_get(url, timeout=10)
    if r["code"] != 200 or not r["body"]:
        return f"Website nicht erreichbar (HTTP {r.get('code', 0)})."

    raw = r["body"]
    emails_found: set = set()

    # --- Joomla E-Mail-Obfuskierung entschlüsseln ---
    # Muster 1a: var addyXXX = 'user' + '@'; addyXXX = addyXXX + 'domain' + '.' + 'tld';
    for m in re.finditer(r"var\s+(addy\w+)\s*=\s*'([^']+)'\s*\+\s*'@'\s*;", raw):
        varname, user = m.group(1), m.group(2)
        domain_m = re.search(
            rf"{re.escape(varname)}\s*=\s*{re.escape(varname)}\s*\+"
            r"\s*'([^']+)'\s*\+\s*'\.'\s*\+\s*'([^']+)'\s*;",
            raw,
        )
        if domain_m:
            emails_found.add(f"{user}@{domain_m.group(1)}.{domain_m.group(2)}")

    # Muster 1b: var addyXXX = 'user@domain.tld' (direkt, nur aufgeteilt)
    for m in re.finditer(r"var\s+addy\w+\s*=\s*'([^'@]+@[^']+)'\s*;", raw):
        candidate = m.group(1).replace("' + '", "")
        if "@" in candidate and "." in candidate.split("@")[-1]:
            emails_found.add(candidate)

    # Muster 2: mailto-Links mit zusammengesetzten Strings (ältere Joomla)
    for m in re.finditer(
        r"'ma'\s*\+\s*'il'\s*\+\s*'to'\s*[+:,'\s]*([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})",
        raw,
    ):
        emails_found.add(m.group(1))

    # Muster 3: Standard mailto:-Links im HTML
    for m in re.finditer(
        r'mailto:([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})',
        raw,
        re.IGNORECASE,
    ):
        emails_found.add(m.group(1))

    # Muster 4: Plain-Text – NUR wenn local-part >= 4 Zeichen und ASCII-only
    # (vermeidet False Positives durch Umlaut-Abschnitte wie "ttenverwaltung@...")
    for m in re.finditer(r'(?<![a-zA-ZÀ-ž])([a-zA-Z0-9][a-zA-Z0-9._%+\-]{3,}@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})(?![a-zA-Z0-9])', raw):
        candidate = m.group(1)
        if not any(x in candidate for x in ["example", "domain", "test", ".js", ".css", ".png", "jquery", "schema"]):
            emails_found.add(candidate)

    # HTML in Text umwandeln
    text = re.sub(r'<script[^>]*>.*?</script>', ' ', raw, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', ' ', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = _html.unescape(text)
    text = re.sub(r'\s+', ' ', text).strip()

    # Relevante Abschnitte bevorzugen (Kontakt, Reservation, Buchung)
    keywords = ["kontakt", "reservation", "buchung", "telefon", "tel.", "öffnungszeit",
                "bewartet", "mail", "e-mail", "auskunft"]
    sentences = re.split(r'(?<=[.!?])\s+', text)
    relevant = [s for s in sentences if any(k in s.lower() for k in keywords)]
    excerpt = " ".join(relevant[:6]) if relevant else text[:600]

    result_parts = []
    if emails_found:
        result_parts.append("E-Mail: " + ", ".join(sorted(emails_found)))
    result_parts.append(excerpt[:700])
    result = "\n".join(result_parts)

    cache_set(ck, result, 3600)
    return result


def _tool_web_search(query: str) -> str:
    """DuckDuckGo-Suche für den Chatbot."""
    from urllib.parse import quote
    import re as _re
    from .http import http_get
    from .config import CONFIG as _cfg
    ck = cache_key("chat_ddg", query.lower().strip())
    cached = cache_get(ck)
    if cached:
        return cached
    url = f"{_cfg['duckduckgo']['endpoint']}?q={quote(query)}&kl=ch-de"
    r = http_get(url, 8)
    if r["code"] != 200 or not r["body"]:
        return "Keine Suchergebnisse gefunden."

    from urllib.parse import unquote as _unquote, urlparse as _urlparse

    # URLs und Snippets gemeinsam extrahieren
    result_blocks = _re.findall(
        r'uddg=([^"&]+).*?class="result__snippet"[^>]*>(.*?)</a>',
        r["body"],
        _re.DOTALL,
    )

    lines = []
    seen_hosts: set = set()
    for enc, snippet in result_blocks[:5]:
        u = _unquote(enc)
        if not _re.match(r"^https?://", u):
            continue
        host = (_urlparse(u).hostname or "").lower()
        if host in seen_hosts:
            continue
        seen_hosts.add(host)
        clean_snippet = _re.sub(r"<[^>]+>", "", snippet).strip()[:200]
        lines.append(f"- {u}\n  {clean_snippet}")

    if lines:
        result = "Gefundene Seiten:\n" + "\n".join(lines[:4])
        cache_set(ck, result, 3600)
        return result
    return "Keine Suchergebnisse gefunden."


def build_hut_context(huts: list) -> str:
    """Kompakter Kontext-String aus Suchergebnissen für den Chatbot."""
    lines = ["Aktuelle Suchergebnisse – Schweizer Berghütten:"]
    for h in huts:
        w = h.get("weather", {})
        sat = w.get("sat", {})
        sun = w.get("sun", {})
        wiki = (h.get("wikipediaText") or "")[:250]

        season = h.get("seasonInfo") or {}
        season_bits = []
        if season.get("bewartet_text"):
            season_bits.append(f"Hütte bewartet: {season['bewartet_text']}")
        if season.get("schutzraum_text"):
            season_bits.append(f"Schutzraum offen: {season['schutzraum_text']}")
        season_line = (
            f"\n  Öffnungszeiten (SAC-Tourenportal): {' | '.join(season_bits)}"
            if season_bits else ""
        )

        availability = h.get("availability") or {}
        avail_line = ""
        if availability:
            avail_count = sum(1 for v in availability.values() if v == "available")
            total_count = len(availability)
            if total_count > 0:
                avail_line = f"\n  Verfügbarkeit (nächste Tage): {avail_count}/{total_count} Tage mit freien Betten"

        website_line = ""
        website_url = h.get("websiteUrl") or h.get("sacBookingUrl")
        if website_url:
            website_line = f"\n  Offizielle Website: {website_url}"

        lines.append(
            f"\n{h['rank']}. {h['name']} ({h.get('elevation', '?')} m, {h.get('region', 'Schweiz')})\n"
            f"  Wetter-Score: {w.get('total', '?')} Punkte\n"
            f"  Samstag: {sat.get('weatherText', '')} {sat.get('tempMax', '')}°/{sat.get('tempMin', '')}°C, "
            f"{sat.get('sunshineHours', '')}h Sonne, {sat.get('precipitation', '')}mm Regen\n"
            f"  Sonntag:  {sun.get('weatherText', '')} {sun.get('tempMax', '')}°/{sun.get('tempMin', '')}°C, "
            f"{sun.get('sunshineHours', '')}h Sonne, {sun.get('precipitation', '')}mm Regen\n"
            f"  Empfehlung: {h.get('recommendation', '')}\n"
            f"  Info: {wiki}"
            f"{season_line}"
            f"{avail_line}"
            f"{website_line}"
        )
    return "\n".join(lines)


def _clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", text)
    text = re.sub(r"_{1,2}([^_]+)_{1,2}", r"\1", text)
    return text


def chat_response(messages: list, context: str) -> str:
    """Multi-Turn-Chat mit Function Calling (Wikipedia + Web-Suche als Tools)."""
    api_key = INFOMANIAK_API_KEY
    if _is_placeholder_key(api_key):
        return "Kein API-Key konfiguriert."

    system = CHAT_SYSTEM_PROMPT + "\n\n" + context
    working_messages = [{"role": "system", "content": system}] + list(messages)

    for _ in range(12):  # max 12 Runden – so viele Tool-Calls wie nötig
        payload = {
            "model": MODEL_NAME,
            "temperature": 0.4,
            "max_tokens": 1500,
            "messages": working_messages,
            "tools": CHAT_TOOLS,
            "tool_choice": "auto",
        }
        r = http_post(
            API_ENDPOINT,
            payload,
            timeout=20,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        if r["code"] != 200 or not r["body"]:
            break
        try:
            j = json.loads(r["body"])
        except json.JSONDecodeError:
            break

        choice = (j.get("choices") or [{}])[0]
        msg = choice.get("message", {})
        finish = choice.get("finish_reason", "")

        # Finale Antwort
        if finish == "stop" or (not msg.get("tool_calls") and msg.get("content")):
            text = msg.get("content") or ""
            return _clean_text(text) or "Fehler beim Abrufen der Antwort."

        # Tool-Calls ausführen
        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            break

        working_messages.append(msg)  # Assistant-Nachricht mit tool_calls

        for tc in tool_calls:
            fn_name = tc.get("function", {}).get("name", "")
            try:
                args = json.loads(tc.get("function", {}).get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            query = args.get("query", "")

            if fn_name == "check_hut_availability":
                result = _tool_check_availability(args.get("hut_name", ""))
            elif fn_name == "search_wikipedia":
                result = _tool_wikipedia(query)
            elif fn_name == "search_web":
                result = _tool_web_search(query)
            elif fn_name == "fetch_hut_website":
                fetch_url = args.get("url", "")
                result = _tool_fetch_website(fetch_url)
            else:
                result = "Unbekanntes Tool."

            working_messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": result,
            })

    return "Fehler beim Abrufen der Antwort – bitte erneut versuchen."
