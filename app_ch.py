"""Schweizer Hütten-Finder – Streamlit Frontend (nur CH, SAC priorisiert).

Start mit:  streamlit run app_ch.py
"""
from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from ahfinder.ai import build_hut_context, chat_response
from ahfinder.pipeline_ch import PipelineError, run_search_ch


st.set_page_config(
    page_title="Schweizer Hütten-Finder",
    page_icon="🇨🇭",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ── Passwortschutz ──────────────────────────────────────────────────────────
def _check_password() -> bool:
    """Einfacher Passwortschutz via st.secrets."""
    if st.session_state.get("auth"):
        return True
    st.markdown(
        """
        <div style="max-width:360px;margin:6rem auto;text-align:center;color:white;">
            <div style="font-size:3rem;">🏔️</div>
            <h2 style="color:white;margin-bottom:0.25rem;">Schweizer Hütten-Finder</h2>
            <p style="opacity:0.8;margin-bottom:1.5rem;">Bitte Passwort eingeben</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    col = st.columns([1, 1, 1])[1]
    with col:
        pw = st.text_input("Passwort", type="password", label_visibility="collapsed",
                           placeholder="Passwort eingeben …")
        if pw:
            if pw == st.secrets.get("app_password", ""):
                st.session_state["auth"] = True
                st.rerun()
            else:
                st.error("Falsches Passwort")
    return False


if not _check_password():
    st.stop()
# ────────────────────────────────────────────────────────────────────────────


# ── Custom CSS ──────────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
        .stApp {
            background: linear-gradient(135deg, #c0392b 0%, #8e0000 60%, #5a0000 100%);
        }
        .hero {
            text-align: center;
            color: white;
            padding: 1.5rem 0 2rem 0;
        }
        .hero h1 { font-size: 3rem; font-weight: 700; margin: 0; letter-spacing: -0.02em; }
        .hero p  { font-size: 1.15rem; opacity: 0.9; margin-top: 0.5rem; }
        .hut-card {
            background: rgba(255, 255, 255, 0.96);
            backdrop-filter: blur(10px);
            border-radius: 1rem;
            padding: 1.1rem 1.2rem 1.2rem 1.2rem;
            box-shadow: 0 10px 25px -5px rgba(0,0,0,0.20);
            height: 100%;
            display: flex;
            flex-direction: column;
        }
        .hut-card h3 { margin: 0 0 0.25rem 0; font-size: 1.2rem; color: #1f2937; }
        .hut-meta { color: #6b7280; font-size: 0.85rem; margin-bottom: 0.6rem; }
        .hut-rec {
            font-style: italic; color: #374151; font-size: 0.9rem;
            border-left: 3px solid #c0392b; padding-left: 0.7rem;
            margin-bottom: 0.8rem;
            height: 9rem; overflow-y: auto;
        }
        .hut-wiki {
            font-style: italic; color: #4b5563; font-size: 0.85rem;
            border-left: 3px solid #e5e7eb; padding-left: 0.7rem;
            margin-bottom: 0.8rem;
            height: 5rem; overflow-y: auto;
        }
        .hut-title-block {
            min-height: 3.2rem;
            display: flex; justify-content: space-between; align-items: flex-start; gap: 0.5rem;
        }
        .hut-meta-block {
            min-height: 1.6rem;
        }
        .rank-badge {
            display: inline-block; width: 32px; height: 32px;
            border-radius: 9999px; text-align: center; line-height: 32px;
            font-weight: 700; font-size: 0.9rem;
        }
        .rank-1 { background: #facc15; color: #713f12; }
        .rank-2 { background: #d1d5db; color: #1f2937; }
        .rank-3 { background: #fdba74; color: #7c2d12; }
        .rank-x { background: #f3f4f6; color: #4b5563; }
        .ele-tag {
            display: inline-block; background: rgba(0,0,0,0.7); color: white;
            padding: 0.15rem 0.5rem; border-radius: 0.35rem; font-size: 0.75rem;
            font-weight: 600;
        }
        .sac-badge {
            display: inline-block; background: #c0392b; color: white;
            padding: 0.15rem 0.5rem; border-radius: 0.35rem; font-size: 0.72rem;
            font-weight: 700; letter-spacing: 0.03em;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


# ── Helfer ──────────────────────────────────────────────────────────────────
def next_weekend(today: date | None = None) -> tuple[date, date]:
    today = today or date.today()
    wd = today.weekday()
    if wd == 5:
        return today, today + timedelta(days=1)
    if wd == 6:
        return today - timedelta(days=1), today
    days_to_sat = 5 - wd
    sat = today + timedelta(days=days_to_sat)
    return sat, sat + timedelta(days=1)


def _weather_badge_html(d: dict, label: str) -> str:
    icon = d["weatherIcon"]
    text = d["weatherText"]
    sun = d["sunshineHours"]
    tmax = round(d["tempMax"])
    tmin = round(d["tempMin"])
    precip = d["precipitation"]
    snow = d["snowfall"]

    if precip > 0.1:
        rain_html = f"<div style='color:#2563eb;font-size:0.85rem;'>🌧️ {precip} mm</div>"
    else:
        rain_html = "<div style='color:#16a34a;font-size:0.85rem;'>💧 Kein Regen</div>"

    snow_html = (
        f"<div style='color:#0284c7;font-size:0.85rem;'>❄️ {snow} cm</div>"
        if snow > 0.1 else ""
    )

    return (
        f"<div style='flex:1;'>"
        f"<div style='font-size:0.72rem;color:#6b7280;margin-bottom:0.2rem;'>{label}</div>"
        f"<div style='border:1px solid rgba(49,51,63,0.2);border-radius:0.5rem;"
        f"padding:0.5rem 0.6rem;box-sizing:border-box;height:8rem;overflow:hidden;'>"
        f"<div style='font-weight:700;font-size:0.95rem;margin-bottom:0.25rem;'>{icon} {text}</div>"
        f"<div style='font-size:0.85rem;'>☀️ <b>{sun} h</b> Sonne</div>"
        f"<div style='font-size:0.85rem;'>🌡️ <b>{tmax}° / {tmin}° C</b></div>"
        f"{rain_html}{snow_html}"
        f"</div></div>"
    )


def render_card(item: dict) -> None:
    rank = item["rank"]
    rank_cls = {1: "rank-1", 2: "rank-2", 3: "rank-3"}.get(rank, "rank-x")
    ele = f"{item['elevation']} m" if item.get("elevation") else "— m"
    img = item.get("wikipediaImage")
    wiki_url = item.get("wikipediaUrl")
    website = item.get("websiteUrl")
    sac_url = item.get("sacBookingUrl")
    is_sac = item.get("isSac", False)

    IMG_HEIGHT = 220

    with st.container():
        if img:
            st.markdown(
                f"<div style='height:{IMG_HEIGHT}px;overflow:hidden;border-radius:0.6rem;'>"
                f"<img src='{img}' style='width:100%;height:100%;object-fit:cover;display:block;'>"
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f"<div style='height:{IMG_HEIGHT}px;background:linear-gradient(135deg,#c0392b,#8e0000);"
                f"border-radius:0.6rem;display:flex;flex-direction:column;"
                f"align-items:center;justify-content:center;padding:0 1rem;'>"
                f"<div style='font-size:2.5rem;color:white;margin-bottom:0.3rem;'>🏔️</div>"
                f"<div style='color:white;font-size:0.8rem;text-align:center;opacity:0.9;'>"
                f"{item['name']}</div></div>",
                unsafe_allow_html=True,
            )

        meta = item.get("region") or "Schweiz"
        if item.get("operator"):
            meta += f" · {item['operator']}"

        sac_html = "<span class='sac-badge'>SAC</span> " if is_sac else ""

        season = item.get("seasonInfo") or {}

        # Tagesgenaue Verfügbarkeit wird on-demand geprüft (nicht automatisch)
        # Session state für Verfügbarkeitsabruf
        if "availability_cache" not in st.session_state:
            st.session_state.availability_cache = {}

        hut_name = item["name"]
        cached_availability = st.session_state.availability_cache.get(hut_name)
        avail_html = bool(cached_availability)

        sat_html = _weather_badge_html(item["weather"]["sat"], "Samstag")
        sun_html = _weather_badge_html(item["weather"]["sun"], "Sonntag")
        wiki_html = item.get("wikipediaText") or ""

        # Saison- und Verfügbarkeitsinfos als Prefix in die scrollbare Empfehlung integrieren
        rec_prefix = ""
        if season.get("bewartet_text"):
            season_line = f"🛎️ Bewartet: <b>{season['bewartet_text']}</b>"
            if season.get("schutzraum_text"):
                season_line += f" &nbsp;·&nbsp; 🚪 Schutzraum: <b>{season['schutzraum_text']}</b>"
            rec_prefix += (
                f"<div style='font-size:0.78rem;color:#374151;"
                f"border-bottom:1px solid #e5e7eb;padding-bottom:0.35rem;margin-bottom:0.4rem;'>"
                f"{season_line}</div>"
            )
        if avail_html:
            avail_count = sum(1 for v in cached_availability.values() if v == "available")
            total_count = len(cached_availability)
            pct = int(100 * avail_count / total_count) if total_count else 0
            status_text = (
                f"✅ {avail_count}/{total_count} Tage frei" if pct >= 50 else
                f"⚠️ {avail_count}/{total_count} Tage frei" if pct > 0 else
                "❌ Voll besetzt"
            )
            rec_prefix += (
                f"<div style='font-size:0.78rem;color:#374151;margin-bottom:0.4rem;'>"
                f"{status_text}</div>"
            )

        st.markdown(
            f"<div class='hut-card'>"
            f"<div class='hut-title-block'>"
            f"<h3>{sac_html}{item['name']}</h3>"
            f"<span class='rank-badge {rank_cls}'>#{rank}</span>"
            f"</div>"
            f"<div class='hut-meta hut-meta-block'>{meta} "
            f"<span class='ele-tag'>📐 {ele}</span></div>"
            f"<div class='hut-rec'>{rec_prefix}{item['recommendation']}</div>"
            f"<div style='display:flex;gap:0.5rem;margin-bottom:0.8rem;'>{sat_html}{sun_html}</div>"
            f"<div class='hut-wiki'>{wiki_html}</div>",
            unsafe_allow_html=True,
        )

        # Routing
        st.link_button(
            "🧭 Route planen (Start selbst eingeben)",
            item["routingUrl"],
            use_container_width=True,
        )

        # Website / SAC-Buchung
        if website:
            st.link_button(
                "🏕️ Offizielle Website / Buchung",
                website,
                type="primary",
                use_container_width=True,
            )
        elif sac_url:
            st.link_button(
                "🏔️ SAC Hütten­verzeichnis",
                sac_url,
                type="primary",
                use_container_width=True,
            )
        else:
            st.markdown(
                "<div style='text-align:center;padding:0.5rem;background:#f3f4f6;"
                "border-radius:0.5rem;font-size:0.8rem;color:#6b7280;'>"
                "Keine offizielle Website verifiziert</div>",
                unsafe_allow_html=True,
            )

        b1, b2 = st.columns(2)
        b1.link_button(
            "🗺️ Maps",
            f"https://www.google.com/maps?q={item['lat']},{item['lon']}",
            use_container_width=True,
        )
        if wiki_url:
            b2.link_button("📖 Wikipedia", wiki_url, use_container_width=True)
        else:
            b2.markdown(
                "<div style='text-align:center;padding:0.4rem;background:#f8fafc;"
                "border-radius:0.5rem;font-size:0.75rem;color:#94a3b8;'>"
                "📖 Wikipedia</div>",
                unsafe_allow_html=True,
            )

        st.markdown("</div>", unsafe_allow_html=True)


# ── Header ──────────────────────────────────────────────────────────────────
default_sat, default_sun = next_weekend()
st.markdown(
    "<div class='hero'>"
    "<h1>🇨🇭 Schweizer Hütten-Finder</h1>"
    "<p>SAC-Hütten · Open-Meteo Wetter · KI-Empfehlung · nur Schweiz</p>"
    "</div>",
    unsafe_allow_html=True,
)

with st.container():
    c1, c2, c3 = st.columns([1, 1, 1])
    sat_date = c1.date_input("Samstag", value=default_sat, min_value=date.today())
    sun_date = c2.date_input("Sonntag", value=default_sun, min_value=date.today())
    with c3:
        st.markdown("<div style='height:28px;'></div>", unsafe_allow_html=True)
        search_clicked = st.button(
            "🔍 Aktuelle Top-Hütten finden",
            type="primary",
            use_container_width=True,
        )
        only_photos = st.toggle(
            "Nur Hütten mit Foto",
            value=False,
            help="Zeigt nur Hütten, für die ein Wikipedia-/Wikimedia-Bild gefunden wurde.",
        )
        only_sac = st.toggle(
            "Nur SAC-Hütten",
            value=False,
            help="Filtert auf offizielle SAC/CAS-Hütten.",
        )

st.markdown(
    f"<p style='text-align:center;color:white;opacity:0.85;margin-top:0.5rem;'>"
    f"Wochenende: <strong>{sat_date.strftime('%a, %d. %B %Y')}</strong> – "
    f"<strong>{sun_date.strftime('%a, %d. %B %Y')}</strong></p>",
    unsafe_allow_html=True,
)


# ── Suche ───────────────────────────────────────────────────────────────────
if search_clicked:
    sat_str = sat_date.isoformat()
    sun_str = sun_date.isoformat()
    if sun_date <= sat_date:
        st.error("Der Sonntag muss nach dem Samstag liegen.")
    else:
        status = st.status(
            "Suche läuft (erster Aufruf kann 20–40 Sek. dauern, danach gecacht) …",
            expanded=True,
        )
        try:
            data = run_search_ch(
                sat_str,
                sun_str,
                only_photos=only_photos,
                only_sac=only_sac,
                progress=status.write,
            )
        except PipelineError as e:
            status.update(label="Fehler", state="error")
            st.error(str(e))
        except Exception as e:  # noqa: BLE001
            status.update(label="Unerwarteter Fehler", state="error")
            st.exception(e)
        else:
            status.update(
                label=f"Fertig: {data['count']} Hütten gefunden",
                state="complete",
            )
            st.session_state["results_ch"] = data


# ── Ergebnisse ──────────────────────────────────────────────────────────────
data = st.session_state.get("results_ch")
if data:
    if data.get("fallback"):
        st.warning(
            "Overpass API nicht erreichbar – zeige kuratierte SAC-Vorauswahl. "
            "Wetter, Wikipedia und KI-Empfehlung laufen trotzdem normal."
        )

    huts_to_show = data["huts"]

    if only_sac:
        huts_to_show = [h for h in huts_to_show if h.get("isSac")]
    if only_photos:
        huts_to_show = [h for h in huts_to_show if h.get("wikipediaImage")]

    # Immer auf top_n begrenzen
    from ahfinder.config import CONFIG as _cfg
    huts_to_show = huts_to_show[: _cfg["top_n"]]

    # Ränge neu vergeben nach Filterung
    for idx, item in enumerate(huts_to_show, start=1):
        item["rank"] = idx

    if not huts_to_show:
        st.info(
            "Keine Hütten entsprechen den gesetzten Filtern. "
            "Schalte einen Filter aus oder probiere ein anderes Wochenende."
        )
    else:
        st.markdown(
            "<h2 style='color:white;margin-top:1.5rem;'>Top Empfehlungen – Schweiz</h2>"
            "<p style='color:white;opacity:0.8;'>"
            f"{data['weekend']['satLabel']} – {data['weekend']['sunLabel']}</p>",
            unsafe_allow_html=True,
        )
        for i in range(0, len(huts_to_show), 3):
            row = huts_to_show[i : i + 3]
            cols = st.columns(3, gap="medium")
            for col, item in zip(cols, row):
                with col:
                    render_card(item)

        # ── Chatbot ─────────────────────────────────────────────────────────
        st.markdown(
            "<h2 style='color:white;margin-top:2rem;'>💬 Fragen zu den Hütten</h2>"
            "<p style='color:white;opacity:0.8;margin-bottom:1rem;'>"
            "Stelle Fragen zu den Suchergebnissen – das KI-Modell kennt "
            "Wetter, Lage und Beschreibungen aller angezeigten Hütten.</p>",
            unsafe_allow_html=True,
        )

        if "chat_history" not in st.session_state:
            st.session_state["chat_history"] = []

        # Chat-Verlauf anzeigen
        for msg in st.session_state["chat_history"]:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])

        # Eingabe
        if user_input := st.chat_input("Frage stellen …"):
            st.session_state["chat_history"].append(
                {"role": "user", "content": user_input}
            )
            with st.chat_message("user"):
                st.write(user_input)

            context = build_hut_context(huts_to_show)
            with st.chat_message("assistant"):
                with st.spinner(""):
                    answer = chat_response(
                        st.session_state["chat_history"], context
                    )
                st.write(answer)

            st.session_state["chat_history"].append(
                {"role": "assistant", "content": answer}
            )
