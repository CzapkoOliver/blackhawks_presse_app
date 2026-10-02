"""
app.py
------
Die Streamlit-Oberflaeche der Presse-Vorbereitungs-App fuer die Passau Black Hawks.

Fuehrt alle Bausteine zusammen:
- spieldaten.py       -> Endergebnis, Zuschauer, Schiedsrichter, Schuesse, Trainer
- spielplan.py        -> naechste zwei Spiele beider Mannschaften
- trainer_lookup.py   -> Nationalitaet/Sprache der Trainer
- fragen_generator.py -> Pressekonferenz-Fragen per Claude API (zweisprachig bei Bedarf)
- live_uebersetzer.py -> Live-Untertitel Englisch -> Deutsch waehrend der Pressekonferenz
- nachbericht_generator.py -> Druckfertiger Nachbericht (Headline, Text, O-Ton, Statistik)
- nachbericht_docx.py      -> Export des Nachberichts als Word-Datei (.docx)

Die Vereinsfarben (Schwarz, Rot, Weiss) werden ueber .streamlit/config.toml
gesetzt - diese Datei muss im selben Ordner wie app.py liegen (bzw. beim
Hochladen zu GitHub mit hochgeladen werden). Das Vereinslogo wird aus
"vereinslogo.jpg" (ebenfalls im selben Ordner) eingebettet.

LAYOUT: Dashboard-Stil mit einklappbarer Sidebar (Streamlits eingebaute
Sidebar-Einklapp-Funktion, kein eigener Code noetig), einer immer sichtbaren
Spielkarte + Kennzahlen-Kacheln sowie Tabs fuer Pressefragen/Live-
Uebersetzer/Nachbericht - wie im mit dem Verein abgestimmten Mockup.

Start ueber das Terminal mit: streamlit run app.py
"""

import base64
import time
from datetime import datetime
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

import spieldaten
import spielplan
import trainer_lookup
import fragen_generator
import live_uebersetzer
import nachbericht_generator
import nachbericht_docx

UNSER_TEAM = "EHF Passau Black Hawks"
PRESSESPRECHER_NAME = "Oliver Czapko"
PRESSESPRECHER_TITEL = "Stadion- und Pressesprecher"

VEREINSLOGO_PFAD = Path(__file__).resolve().parent / "vereinslogo.jpg"

# Direkt nach Spielende dauert es auf DEB LIVE manchmal noch ein paar Minuten,
# bis die Seite den Spielstatus tatsaechlich auf "beendet" umstellt. Deshalb
# hier nicht sofort aufgeben, sondern automatisch ein paar Mal erneut
# versuchen, bevor eine Fehlermeldung kommt.
MAX_VERSUCHE = 5
WARTEZEIT_SEKUNDEN = 30


@st.cache_resource
def _playwright_browser_sicherstellen() -> bool:
    """
    Stellt sicher, dass der Chromium-Browser fuer Playwright installiert ist.
    Auf dem eigenen Rechner ist das schon durch "playwright install chromium"
    erledigt (siehe Schritt 1). Auf Streamlit Community Cloud existiert diese
    Installation aber nicht automatisch - deshalb wird sie hier beim ersten
    Start der App einmalig nachgeholt. @st.cache_resource sorgt dafuer, dass
    das nur einmal pro laufender App passiert, nicht bei jedem Klick.
    """
    import subprocess
    import sys

    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=False)
    return True


@st.cache_data
def _vereinslogo_als_data_url() -> str | None:
    """Liest das Vereinslogo einmalig ein und wandelt es in eine data:-URL um."""
    if not VEREINSLOGO_PFAD.exists():
        return None
    inhalt = VEREINSLOGO_PFAD.read_bytes()
    kodiert = base64.b64encode(inhalt).decode()
    return f"data:image/jpeg;base64,{kodiert}"


_playwright_browser_sicherstellen()
VEREINSLOGO_URL = _vereinslogo_als_data_url()

st.set_page_config(page_title="Black Hawks Presse-Dashboard", page_icon="🏒", layout="wide")

# ---------------------------------------------------------------------------
# Globales Erscheinungsbild: eigene Schriftarten (Space Grotesk fuer
# Ueberschriften/Zahlen, Inter fuer Fliesstext) sowie kleine Bausteine
# (Karten, Label) fuer die Stat-Kacheln/Panels weiter unten. Bewusst KEINE
# Eingriffe in Streamlits interne DOM-Struktur - nur eigene, selbst erzeugte
# HTML-Bloecke werden gestylt.
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Inter:wght@400;500;600&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    .bh-value { font-family: 'Space Grotesk', sans-serif; font-weight: 700; }
    .bh-label {
        font-family: 'Inter', sans-serif; font-size: 11px; font-weight: 600;
        letter-spacing: 0.08em; text-transform: uppercase; color: #9a9a9a;
    }
    .bh-card { background: #1e1e1e; border-radius: 12px; padding: 14px 16px; }
    .bh-card-grid { display: grid; gap: 12px; margin-bottom: 4px; }
    .bh-section-titel {
        display: flex; align-items: center; gap: 8px; font-family: 'Space Grotesk', sans-serif;
        font-weight: 700; font-size: 15px; color: #ffffff; margin: 0 0 12px 0;
    }
    .bh-reihe {
        display: flex; justify-content: space-between; gap: 10px; font-size: 13px;
        padding: 7px 0; border-bottom: 1px solid #2a2a2a;
    }
    .bh-reihe:last-child { border-bottom: none; }
    .bh-reihe .bh-k { color: #9a9a9a; }
    .bh-reihe .bh-v { font-weight: 600; text-align: right; }
    .bh-gruppen-label {
        font-size: 10.5px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em;
        color: #C8102E; margin: 10px 0 4px 0;
    }
    .bh-gruppen-label:first-child { margin-top: 0; }
    .bh-nav { display: flex; flex-direction: column; gap: 3px; }
    .bh-nav-item {
        display: flex; align-items: center; gap: 12px; padding: 11px 12px; border-radius: 10px;
        font-size: 13.5px; font-weight: 500; color: #8a8a8f; text-decoration: none; white-space: nowrap;
    }
    .bh-nav-item:hover { background: #1c1c1f; color: #e4e4e7; }
    .bh-nav-item.active { background: #C8102E; color: #fff; font-weight: 600; }
    .bh-nav-item svg { flex: 0 0 auto; opacity: .9; }
    /* Beim Klick auf einen Menuepunkt springt der Browser zur jeweiligen
       Sprungmarke - ohne diesen Abstand landet die Ueberschrift genau am
       oberen Bildschirmrand und wird von Streamlits fixer Kopfzeile
       (Deploy-Button etc.) teilweise verdeckt/abgeschnitten. */
    [id^="bh-"] { scroll-margin-top: 120px; }
    </style>
    """,
    unsafe_allow_html=True,
)

# Kleine, wiederverwendbare Inline-Icons (statt Emoji) fuer die
# Abschnittsueberschriften - passend zum vorher abgestimmten Mockup.
BH_ICON_PFEIFE = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#C8102E" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="5"/><path d="M20 21a8 8 0 0 0-16 0"/></svg>'
BH_ICON_KALENDER = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#C8102E" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>'
BH_ICON_SPRECHBLASE = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#C8102E" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>'

# Icons fuer die Navigation in der Sidebar (gleiche Linienstaerke wie oben,
# hier aber in der jeweiligen Nav-Item-Farbe statt fest Rot - siehe
# bh_nav_item() weiter unten).
BH_NAV_ICON_UEBERSICHT = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="4" height="9"/><rect x="10" y="6" width="4" height="14"/><rect x="17" y="3" width="4" height="17"/></svg>'
BH_NAV_ICON_FRAGEN = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>'
BH_NAV_ICON_UEBERSETZER = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 8l6 6M4 14l6-6 2-3M2 5h12M7 2h1M22 22l-5-10-5 10M14 18h6"/></svg>'
BH_NAV_ICON_NACHBERICHT = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M9 13h6M9 17h6M9 9h1"/></svg>'


def bh_nav_item(icon: str, label: str, anker: str, aktiv: bool = False) -> str:
    """Rendert einen Eintrag im Sidebar-Menue als Sprungmarke (#anker) zum
    jeweiligen Abschnitt auf der Seite - optisch wie im abgestimmten Mock Up."""
    klasse = "bh-nav-item active" if aktiv else "bh-nav-item"
    return f'<a class="{klasse}" href="#{anker}">{icon}<span>{label}</span></a>'


def bh_abschnitt_titel(icon: str, text: str) -> None:
    """Rendert eine kleine Abschnittsueberschrift mit Icon statt Emoji."""
    st.markdown(f'<div class="bh-section-titel">{icon}<span>{text}</span></div>', unsafe_allow_html=True)


def bh_karten_zeile(karten: list[tuple[str, str]], spalten: int = 2) -> None:
    """
    Rendert eine Reihe kleiner, abgerundeter Stat-Kacheln (Label + grosser
    Wert) statt der Standard-st.metric-Kacheln - optisch angelehnt an das
    zuvor abgestimmte Mockup.
    """
    zellen = "".join(
        f'<div class="bh-card"><div class="bh-label">{label}</div>'
        f'<div class="bh-value" style="font-size:22px; color:#ffffff; margin-top:4px;">{wert}</div></div>'
        for label, wert in karten
    )
    st.markdown(
        f'<div class="bh-card-grid" style="grid-template-columns: repeat({spalten}, minmax(0, 1fr));">{zellen}</div>',
        unsafe_allow_html=True,
    )


def bh_team_wappen_html(team_name: str, logo_url: str | None, groesse: int = 34) -> str:
    """
    Liefert HTML fuer das Vereinswappen eines Teams: fest hinterlegtes
    eigenes Logo fuer die Black Hawks, andernfalls das von der DEB-LIVE-Seite
    automatisch mitgelesene Wappen (sofern gefunden), sonst ersatzweise ein
    schlichtes Kuerzel-Abzeichen - NIE ein falsches/fremdes Logo.
    """
    if team_name == UNSER_TEAM and VEREINSLOGO_URL:
        return (
            f'<img src="{VEREINSLOGO_URL}" style="width:{groesse}px; height:{groesse}px; '
            f'border-radius:50%; object-fit:cover; flex-shrink:0;">'
        )
    if logo_url:
        return (
            f'<img src="{logo_url}" style="width:{groesse}px; height:{groesse}px; '
            f'border-radius:50%; object-fit:cover; flex-shrink:0;" '
            f'onerror="this.style.display=\'none\';">'
        )
    kuerzel = "".join(wort[0] for wort in team_name.split()[:3]).upper() or "?"
    return (
        f'<div style="width:{groesse}px; height:{groesse}px; border-radius:50%; background:#2c2c30; '
        f'display:flex; align-items:center; justify-content:center; font-size:11px; font-weight:700; '
        f'color:#d4d4d8; flex-shrink:0;">{kuerzel}</div>'
    )


# ---------------------------------------------------------------------------
# Sidebar: Vereinslogo, Spielbericht-Link + "Daten laden" (die zentrale
# Eingabe gehoert als globale Steuerung in die Sidebar), Pressesprecher-Chip.
# Streamlits Sidebar laesst sich bereits eingebaut per Klick einklappen
# (Pfeil oben) - dafuer ist kein eigener Code noetig.
# ---------------------------------------------------------------------------
with st.sidebar:
    if VEREINSLOGO_URL:
        st.markdown(
            f'<img src="{VEREINSLOGO_URL}" style="width:64px; height:64px; border-radius:50%; '
            f'object-fit:cover; display:block; margin-bottom:10px;">',
            unsafe_allow_html=True,
        )
    st.markdown(
        '<div class="bh-value" style="font-size:16px; line-height:1.25; color:#fff;">'
        "EHF Passau<br>Black Hawks</div>"
        '<div class="bh-label" style="color:#C8102E; margin-top:2px;">Presse-Dashboard</div>',
        unsafe_allow_html=True,
    )
    st.divider()

    st.markdown(
        '<div class="bh-nav">'
        + bh_nav_item(BH_NAV_ICON_UEBERSICHT, "Spielübersicht", "bh-spieluebersicht", aktiv=True)
        + bh_nav_item(BH_NAV_ICON_FRAGEN, "Pressefragen", "bh-pressefragen")
        + bh_nav_item(BH_NAV_ICON_UEBERSETZER, "Live-Übersetzer", "bh-liveuebersetzer")
        + bh_nav_item(BH_NAV_ICON_NACHBERICHT, "Nachbericht", "bh-nachbericht")
        + "</div>",
        unsafe_allow_html=True,
    )
    st.divider()

    url = st.text_input(
        "Link zum Spielbericht",
        placeholder="https://deb-online.live/spielbericht/?gameId=...&divisionId=...",
        help="Aus der Browser-Adressleiste auf deb-online.live kopieren.",
    )
    laden = st.button("Daten laden", type="primary", use_container_width=True)

    st.divider()
    st.markdown(
        f'<div style="font-size:13px; font-weight:600; color:#fff;">{PRESSESPRECHER_NAME}</div>'
        f'<div style="font-size:11.5px; color:#9a9a9a;">{PRESSESPRECHER_TITEL}</div>',
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------------------
# Datenladen (ausgeloest ueber den Button in der Sidebar)
# ---------------------------------------------------------------------------
if laden:
    if not url:
        st.warning("Bitte zuerst einen Link zum Spielbericht einfügen.")
        st.stop()

    # Direkt nach Spielende zeigt DEB LIVE das Spiel manchmal noch kurz
    # als "laeuft" an, bevor die Seite auf "beendet" umschaltet. Deshalb
    # hier mehrmals mit Wartezeit dazwischen versuchen, bis entweder das
    # Spiel als "beendet" markiert ist ODER die Versuche aufgebraucht
    # sind. Sind Teamnamen/Ergebnis schon lesbar, aber das Spiel laeuft
    # noch, wird NICHT einfach ein Fehler angezeigt: stattdessen wird
    # nach dem letzten Versuch der aktuelle Zwischenstand ausgewertet
    # und deutlich als "noch nicht offiziell beendet" gekennzeichnet.
    daten = None
    for versuch in range(1, MAX_VERSUCHE + 1):
        with st.spinner(f"Lade Spieldaten von DEB LIVE ... (Versuch {versuch}/{MAX_VERSUCHE})"):
            roher_text_spielverlauf, roher_text, logos = spieldaten.hole_sichtbaren_text(url)
            daten = spieldaten.parse_spielbericht(roher_text, roher_text_spielverlauf)

        vollstaendig_lesbar = daten["heimteam"] and daten["gastteam"] and daten["endergebnis"]

        if vollstaendig_lesbar and daten["ist_beendet"]:
            break  # offiziell beendet - fertig, kein weiterer Versuch noetig

        if versuch < MAX_VERSUCHE:
            if vollstaendig_lesbar:
                warte_text = (
                    f"Spiel laeuft laut DEB LIVE noch (Status: {daten['status']}) - "
                    f"warte {WARTEZEIT_SEKUNDEN} Sekunden auf das offizielle Ende ..."
                )
            else:
                warte_text = (
                    f"Seite konnte noch nicht ausgelesen werden - "
                    f"warte {WARTEZEIT_SEKUNDEN} Sekunden und versuche es erneut ..."
                )
            with st.spinner(warte_text):
                time.sleep(WARTEZEIT_SEKUNDEN)

    if not daten["heimteam"] or not daten["gastteam"] or not daten["endergebnis"]:
        st.error(
            f"Die Seite konnte auch nach {MAX_VERSUCHE} Versuchen nicht richtig ausgelesen "
            "werden. Bitte pruefen, ob der Link stimmt."
        )
        # Diagnose-Hilfe: den kompletten rohen Seitentext anzeigen, damit
        # er bei Bedarf einfach kopiert und zur Fehlersuche weitergegeben
        # werden kann - ohne dass dafuer lokal Python/das Terminal
        # gebraucht wird (wichtig z.B. direkt am Spielfeldrand).
        with st.expander("Rohtext der Seite anzeigen (zur Fehlersuche)"):
            st.text_area(
                "Kompletter ausgelesener Seitentext",
                value=roher_text,
                height=400,
            )
        st.stop()

    if not daten["ist_beendet"]:
        st.warning(
            f"⚠️ Achtung: Laut DEB LIVE ist dieses Spiel noch nicht offiziell beendet "
            f"(aktueller Status: {daten['status'] or 'unbekannt'}). Angezeigt wird der "
            "aktuelle Zwischenstand - Zahlen koennen sich bis zum echten Spielende noch "
            "aendern. Danach am besten nochmal auf 'Daten laden' klicken."
        )

    gegner = daten["gastteam"] if daten["heimteam"] == UNSER_TEAM else daten["heimteam"]

    with st.spinner("Lade Spielplan ..."):
        plan_text = spielplan.hole_sichtbaren_text(spielplan.SPIELPLAN_URL)
        alle_spiele = spielplan.parse_spielplan(plan_text)
    # Rohtext merken (nicht nur bei Fehlern) - damit bei "0 Spiele erkannt"
    # genau nachvollzogen werden kann, was Playwright auf der Spielplan-Seite
    # tatsaechlich gesehen hat (siehe Diagnose-Hinweis unten bei "Naechste
    # Spiele").
    st.session_state["roher_text_spielplan"] = plan_text
    st.session_state["spielplan_anzahl"] = len(alle_spiele)

    heute = datetime.now()
    naechste_unser_team = spielplan.naechste_spiele(alle_spiele, UNSER_TEAM, heute)
    naechste_gegner = spielplan.naechste_spiele(alle_spiele, gegner, heute)

    # Diagnose-Hinweis: Falls der Spielplan insgesamt nicht (vollstaendig)
    # ausgelesen werden konnte, wuerden bei JEDER Mannschaft die naechsten
    # Spiele fehlen - das faellt so leichter auf, statt einfach
    # stillschweigend eine leere Liste anzuzeigen.
    if not alle_spiele:
        st.caption(
            "⚠️ Hinweis: Der Spielplan konnte diesmal nicht ausgelesen werden "
            "(0 Spiele erkannt) - deshalb fehlen unten die naechsten Spiele. "
            "Das kann an der Seite selbst liegen (z.B. langsam geladen). "
            "Bitte oben nochmal auf 'Daten laden' klicken."
        )
    elif not naechste_unser_team and not naechste_gegner:
        st.caption(
            f"ℹ️ Spielplan wurde ausgelesen ({len(alle_spiele)} Spiele insgesamt), "
            "aber fuer keines der beiden Teams wurden kommende Spiele gefunden. "
            "Moeglich, dass die Teamnamen auf der Spielplan-Seite anders "
            "geschrieben sind (z.B. mit/ohne Umlaut)."
        )

    heim_info = trainer_lookup.hole_nationalitaet_und_sprache(daten["trainer_heim"] or "")
    gast_info = trainer_lookup.hole_nationalitaet_und_sprache(daten["trainer_gast"] or "")

    # Alles in den Session-State speichern, damit es bei jedem weiteren
    # Klick (Pressefragen/Nachbericht generieren) nicht verloren geht.
    st.session_state["daten"] = daten
    st.session_state["gegner"] = gegner
    st.session_state["heim_info"] = heim_info
    st.session_state["gast_info"] = gast_info
    st.session_state["naechste_unser_team"] = naechste_unser_team
    st.session_state["naechste_gegner"] = naechste_gegner
    st.session_state["logos"] = logos
    # Rohtext ebenfalls merken (nicht nur bei Fehlern) - damit bei Bedarf
    # (z.B. falsch/abgekuerzt ausgelesene Spielernamen) auch nach einem
    # ERFOLGREICHEN Laden noch nachvollzogen werden kann, was auf der Seite
    # tatsaechlich stand. Siehe Diagnose-Bereich im Nachbericht-Tab.
    st.session_state["roher_text_spielverlauf"] = roher_text_spielverlauf
    st.session_state["roher_text_spielbericht"] = roher_text
    st.session_state.pop("fragen", None)  # alte Fragen verwerfen bei neuem Spiel
    st.session_state.pop("nachbericht", None)  # alten Nachbericht verwerfen bei neuem Spiel

# ---------------------------------------------------------------------------
# Hauptbereich (Dashboard)
# ---------------------------------------------------------------------------
if "daten" not in st.session_state:
    st.markdown(
        '<div class="bh-value" style="font-size:22px; color:#fff;">Spielübersicht</div>',
        unsafe_allow_html=True,
    )
    st.info("Bitte links in der Sidebar einen Link zum DEB-LIVE-Spielbericht einfügen und auf 'Daten laden' klicken.")
else:
    daten = st.session_state["daten"]
    gegner = st.session_state["gegner"]
    heim_info = st.session_state["heim_info"]
    gast_info = st.session_state["gast_info"]
    naechste_unser_team = st.session_state["naechste_unser_team"]
    naechste_gegner = st.session_state["naechste_gegner"]
    logos = st.session_state.get("logos", {"heim": None, "gast": None})

    heim = daten["heimteam"]
    gast = daten["gastteam"]

    st.markdown('<div id="bh-spieluebersicht"></div>', unsafe_allow_html=True)

    # ---- Topbar: Titel + Status-Pille ----
    status_ist_beendet = daten["ist_beendet"]
    status_farbe = "#1a7f4e" if status_ist_beendet else "#C8A51A"
    status_text_pill = "Spiel beendet" if status_ist_beendet else (daten["status"] or "Status unbekannt")
    st.markdown(
        f"""
        <div style="display:flex; align-items:center; justify-content:space-between; gap:16px;
                    flex-wrap:wrap; margin-bottom:18px;">
            <div>
                <div class="bh-value" style="font-size:22px; color:#fff;">Spielübersicht</div>
                <div style="color:#9a9a9a; font-size:13px; margin-top:2px;">{heim} – {gast}</div>
            </div>
            <div style="display:flex; align-items:center; gap:7px; background:#1a1a1a; border:1px solid #2e2e2e;
                        padding:7px 13px; border-radius:999px; font-size:12.5px; font-weight:600; color:#fff;">
                <span style="width:7px; height:7px; border-radius:50%; background:{status_farbe};"></span>
                {status_text_pill}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ---- Spielkarte: Wappen, Teamnamen, Endergebnis ----
    if daten["zuschauer"]:
        try:
            zuschauer_formatiert = f"{int(daten['zuschauer']):,}".replace(",", ".")
        except ValueError:
            zuschauer_formatiert = daten["zuschauer"]
        zuschauer_text = f"{zuschauer_formatiert} Zuschauer"
    else:
        zuschauer_text = status_text_pill

    heim_wappen = bh_team_wappen_html(heim, logos.get("heim"))
    gast_wappen = bh_team_wappen_html(gast, logos.get("gast"))

    st.markdown(
        f"""
        <div style="background:linear-gradient(135deg,#0a0a0a,#1c1c1f); border-radius:18px; padding:22px 26px;
                    display:flex; align-items:center; justify-content:space-between; gap:20px; flex-wrap:wrap;
                    margin-bottom:20px;">
            <div style="display:flex; align-items:center; gap:10px; font-family:'Space Grotesk',sans-serif;
                        font-weight:700; font-size:16px; color:#fff; min-width:0;">
                {heim_wappen}<span>{heim}</span>
            </div>
            <div style="text-align:center;">
                <div class="bh-value" style="font-size:34px; color:#fff;">
                    {daten['endergebnis'].replace(':', ' : ')}
                </div>
                <div style="font-size:12px; color:#c7c7cc; margin-top:2px;">{zuschauer_text}</div>
            </div>
            <div style="display:flex; align-items:center; gap:10px; font-family:'Space Grotesk',sans-serif;
                        font-weight:700; font-size:16px; color:#fff; justify-content:flex-end; min-width:0;">
                <span>{gast}</span>{gast_wappen}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ---- KPI-Kacheln ----
    drittel_text = "nicht verfügbar"
    if daten["torfolge_pro_drittel"]:
        teile = []
        for drittel in sorted(daten["torfolge_pro_drittel"]):
            heim_tore, gast_tore = daten["torfolge_pro_drittel"][drittel]
            teile.append(f"{heim_tore}:{gast_tore}")
        drittel_text = " · ".join(teile)

    schuesse_text = (
        f"{daten['schuesse_heim']} : {daten['schuesse_gast']}"
        if daten["schuesse_heim"] is not None and daten["schuesse_gast"] is not None
        else "–"
    )
    strafminuten_text = (
        f"{daten['strafminuten_heim']} : {daten['strafminuten_gast']}"
        if daten["strafminuten_heim"] is not None and daten["strafminuten_gast"] is not None
        else "–"
    )

    bh_karten_zeile(
        [
            ("Schüsse", schuesse_text),
            ("Strafminuten", strafminuten_text),
            ("Drittel 1 · 2 · 3", drittel_text),
            ("Zuschauer", zuschauer_text if daten["zuschauer"] else "–"),
        ],
        spalten=4,
    )
    st.markdown("<div style='margin-top:18px;'></div>", unsafe_allow_html=True)

    # ---- Offizielle & Trainer / Naechste Spiele - immer sichtbar auf der
    #      Spielübersicht, nicht hinter einem Tab versteckt ----
    spalte_links, spalte_rechts = st.columns(2)

    with spalte_links:
        with st.container(border=True):
            bh_abschnitt_titel(BH_ICON_PFEIFE, "Offizielle & Trainer")
            zeilen_html = (
                f'<div class="bh-reihe"><span class="bh-k">Trainer {heim}</span>'
                f'<span class="bh-v">{daten["trainer_heim"] or "unbekannt"} ({heim_info["nationalitaet"]})</span></div>'
                f'<div class="bh-reihe"><span class="bh-k">Trainer {gast}</span>'
                f'<span class="bh-v">{daten["trainer_gast"] or "unbekannt"} ({gast_info["nationalitaet"]})</span></div>'
                f'<div class="bh-reihe"><span class="bh-k">1. Schiedsrichter</span>'
                f'<span class="bh-v">{(daten["schiedsrichter"] or "unbekannt").split(" / ")[0]}</span></div>'
            )
            schiedsrichter_teile = (daten["schiedsrichter"] or "").split(" / ")
            if len(schiedsrichter_teile) > 1:
                zeilen_html += (
                    f'<div class="bh-reihe"><span class="bh-k">2. Schiedsrichter</span>'
                    f'<span class="bh-v">{schiedsrichter_teile[1]}</span></div>'
                )
            linienrichter_teile = (daten["linienrichter"] or "").split(" / ")
            if linienrichter_teile and linienrichter_teile[0]:
                zeilen_html += (
                    f'<div class="bh-reihe"><span class="bh-k">1. Linienrichter</span>'
                    f'<span class="bh-v">{linienrichter_teile[0]}</span></div>'
                )
            if len(linienrichter_teile) > 1:
                zeilen_html += (
                    f'<div class="bh-reihe"><span class="bh-k">2. Linienrichter</span>'
                    f'<span class="bh-v">{linienrichter_teile[1]}</span></div>'
                )
            st.markdown(zeilen_html, unsafe_allow_html=True)
            if heim_info["nationalitaet"] == "unbekannt" or gast_info["nationalitaet"] == "unbekannt":
                st.caption(
                    "Hinweis: Für einen der Trainer fehlt noch ein Eintrag in trainer.csv "
                    "(Nachschlagen z.B. über eliteprospects.com)."
                )

    with spalte_rechts:
        with st.container(border=True):
            bh_abschnitt_titel(BH_ICON_KALENDER, "Nächste Spiele")
            fixture_html = f'<div class="bh-gruppen-label">{UNSER_TEAM}</div>'
            if naechste_unser_team:
                for s in naechste_unser_team:
                    fixture_html += (
                        f'<div class="bh-reihe"><span class="bh-k">{s["datum"].strftime("%d.%m. %H:%M")}</span>'
                        f'<span class="bh-v">{s["heim"]} – {s["gast"]}</span></div>'
                    )
            else:
                fixture_html += '<div class="bh-reihe"><span class="bh-k">keine bekannt</span></div>'
            fixture_html += f'<div class="bh-gruppen-label">{gegner}</div>'
            if naechste_gegner:
                for s in naechste_gegner:
                    fixture_html += (
                        f'<div class="bh-reihe"><span class="bh-k">{s["datum"].strftime("%d.%m. %H:%M")}</span>'
                        f'<span class="bh-v">{s["heim"]} – {s["gast"]}</span></div>'
                    )
            else:
                fixture_html += '<div class="bh-reihe"><span class="bh-k">keine bekannt</span></div>'
            st.markdown(fixture_html, unsafe_allow_html=True)
            if not st.session_state.get("spielplan_anzahl"):
                with st.expander("Rohtext der Spielplan-Seite anzeigen (zur Fehlersuche)"):
                    st.caption(
                        "Zeigt, was Playwright auf der Spielplan-Seite tatsächlich gesehen hat "
                        "- hilfreich, falls hier dauerhaft 'keine bekannt' bzw. '0 Spiele erkannt' "
                        "steht. Bitte den Inhalt bei Bedarf kopieren und weitergeben."
                    )
                    st.text_area(
                        "Seitentext der Spielplan-Seite",
                        value=st.session_state.get("roher_text_spielplan", ""),
                        height=250,
                        key="debug_roher_text_spielplan",
                    )

    st.markdown("<div style='margin-top:8px;'></div>", unsafe_allow_html=True)

    # ---- Hauptbereich: links Tabs (Pressefragen / Nachbericht), rechts
    #      IMMER sichtbar der Live-Uebersetzer - unabhaengig davon, welcher
    #      Tab gerade offen ist. So muessen die Pressefragen nicht erst
    #      weggeklickt werden, um die laufende Live-Uebersetzung zu sehen. ----
    spalte_haupt, spalte_uebersetzer = st.columns([1, 1])

    with spalte_haupt:
        with st.container(border=True):
            st.markdown('<div id="bh-pressefragen"></div>', unsafe_allow_html=True)
            tab_fragen, tab_nachbericht = st.tabs(
                ["Pressekonferenz-Fragen", "Nachbericht für die Presse"]
            )

            with tab_fragen:
                if st.button("Pressefragen generieren", type="primary"):
                    with st.spinner("Claude analysiert das Spiel und formuliert Fragen ..."):
                        fragen = fragen_generator.generiere_pressefragen(
                            daten, heim_info, gast_info, naechste_unser_team, naechste_gegner
                        )
                    st.session_state["fragen"] = fragen

                if "fragen" in st.session_state:
                    with st.container(border=True):
                        st.markdown(st.session_state["fragen"])

            with tab_nachbericht:
                st.markdown('<div id="bh-nachbericht"></div>', unsafe_allow_html=True)
                st.caption(
                    "Erstellt aus den obigen Spieldaten einen druckfertigen Nachbericht "
                    "(Headline, Text, O-Ton, Statistik). Die Live-Übersetzung läuft "
                    "ausschließlich im Browser - die App weiß deshalb nicht automatisch, "
                    "wer gerade spricht. Bitte die gewünschten, bereits übersetzten Zitate "
                    "unten manuell aus dem Live-Übersetzer rechts (Feld 'Transkript als "
                    "Text') in das passende Feld einfügen. Leer gelassene Felder werden "
                    "im O-Ton-Abschnitt als noch zu ergänzen markiert - Claude erfindet "
                    "keine Aussagen."
                )

                # Diagnose-Bereich, falls Spielernamen falsch/abgekuerzt erscheinen
                # (z.B. "MACKINNON J." statt "John MacKinnon"): hier laesst sich der
                # komplette Rohtext der Seite einsehen und kopieren, um zu pruefen,
                # ob der volle Vorname dort ueberhaupt irgendwo steht.
                if "roher_text_spielverlauf" in st.session_state or "roher_text_spielbericht" in st.session_state:
                    with st.expander("Rohtext der Seite anzeigen (z.B. bei falschen/abgekürzten Spielernamen)"):
                        st.caption(
                            "Falls im Nachbericht Vornamen abgekürzt oder falsch erscheinen: "
                            "hier prüfen, ob der volle Vorname überhaupt auf der Seite steht, "
                            "und den Text bei Bedarf zur Fehlersuche weitergeben."
                        )
                        st.text_area(
                            "Spielverlauf (enthält i.d.R. die Torschützen mit vollem Namen)",
                            value=st.session_state.get("roher_text_spielverlauf", ""),
                            height=250,
                            key="debug_roher_text_spielverlauf",
                        )
                        st.text_area(
                            "Spielbericht",
                            value=st.session_state.get("roher_text_spielbericht", ""),
                            height=250,
                            key="debug_roher_text_spielbericht",
                        )

                sperrfrist = st.text_input(
                    "Sperrfrist (falls keine, einfach 'keine' stehen lassen)",
                    value="keine",
                    key="nachbericht_sperrfrist",
                )

                trainer_heim_name = daten["trainer_heim"] or f"Trainer {heim}"
                trainer_gast_name = daten["trainer_gast"] or f"Trainer {gast}"

                spalte_zitat_heim, spalte_zitat_gast = st.columns(2)
                with spalte_zitat_heim:
                    zitat_heim = st.text_area(
                        f"Zitat {trainer_heim_name} ({heim})",
                        placeholder="Wir müssen einfacheres Eishockey spielen.",
                        height=100,
                        key="nachbericht_zitat_heim",
                    )
                with spalte_zitat_gast:
                    zitat_gast = st.text_area(
                        f"Zitat {trainer_gast_name} ({gast})",
                        placeholder="Wir haben zu viele individuelle Fehler gemacht.",
                        height=100,
                        key="nachbericht_zitat_gast",
                    )

                # Aus den beiden benannten Feldern wird intern wieder der Zitate-Text
                # im Format "Name: Zitat" je Zeile gebaut, den nachbericht_generator.py
                # erwartet - so bleibt dort die Logik unveraendert und die Trainer-
                # Namen muessen nicht ein zweites Mal von Hand eingetippt werden.
                zitate_zeilen = []
                if zitat_heim.strip():
                    zitate_zeilen.append(f"{trainer_heim_name}: {zitat_heim.strip()}")
                if zitat_gast.strip():
                    zitate_zeilen.append(f"{trainer_gast_name}: {zitat_gast.strip()}")
                zitate_text = "\n".join(zitate_zeilen)

                if st.button("Nachbericht generieren", type="primary"):
                    with st.spinner("Claude schreibt den Nachbericht ..."):
                        nachbericht = nachbericht_generator.generiere_nachbericht(
                            daten, heim_info, gast_info, zitate_text, sperrfrist
                        )
                    st.session_state["nachbericht"] = nachbericht

                if "nachbericht" in st.session_state:
                    with st.container(border=True):
                        st.markdown(st.session_state["nachbericht"])

                    docx_bytes = nachbericht_docx.nachbericht_zu_docx_bytes(st.session_state["nachbericht"])
                    dateiname = f"nachbericht_{heim}_{gast}.docx".replace(" ", "_")
                    st.download_button(
                        "Nachbericht als Word-Datei (.docx) herunterladen",
                        data=docx_bytes,
                        file_name=dateiname,
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )

    with spalte_uebersetzer:
        with st.container(border=True):
            st.markdown('<div id="bh-liveuebersetzer"></div>', unsafe_allow_html=True)
            bh_abschnitt_titel(BH_ICON_SPRECHBLASE, "Live-Übersetzer")
            st.caption("Läuft während der ganzen Pressekonferenz, Englisch → Deutsch.")
            live_uebersetzer.render()

# ---------------------------------------------------------------------------
# Menue-Steuerung: macht die Sidebar-Links "Pressefragen"/"Nachbericht"
# tatsaechlich funktionsfaehig (schaltet den jeweiligen Tab um, nicht nur
# Hinscrollen) und hebt den aktuell angeklickten Menuepunkt farblich hervor.
# Technischer Hintergrund: Streamlits eigene Tabs lassen sich von aussen
# (z.B. aus der Sidebar) nicht direkt ansteuern - deshalb hier ein kurzes,
# per <iframe> eingebettetes Skript, das auf einen Klick/Sprung zur jeweiligen
# Sprungmarke reagiert und dann den passenden Tab-Button in der eigentlichen
# App per Klick aktiviert bzw. den Menuepunkt hervorhebt.
# ---------------------------------------------------------------------------
components.html(
    """
    <script>
    (function(){
        function aktiviereTabFuerHash(hash){
            var zielText = null;
            if (hash === '#bh-nachbericht') { zielText = 'nachbericht für die presse'; }
            if (hash === '#bh-pressefragen') { zielText = 'pressekonferenz-fragen'; }
            if (!zielText) { return; }
            // Mehrmals versuchen: direkt nach einem Hash-Wechsel sind
            // Streamlits Tab-Buttons manchmal noch nicht (neu) im DOM, z.B.
            // waehrend die Seite gerade neu rendert.
            var versuche = 0;
            var intervall = setInterval(function(){
                versuche += 1;
                try {
                    var tabs = window.parent.document.querySelectorAll('[role="tab"]');
                    for (var i = 0; i < tabs.length; i++) {
                        var text = (tabs[i].textContent || '').trim().toLowerCase();
                        if (text.indexOf(zielText) !== -1) {
                            if (tabs[i].getAttribute('aria-selected') !== 'true') {
                                tabs[i].click();
                            }
                            clearInterval(intervall);
                            return;
                        }
                    }
                } catch (e) {}
                if (versuche > 10) { clearInterval(intervall); }
            }, 150);
        }
        function aktualisiereMenue(hash){
            hash = hash || window.parent.location.hash || '#bh-spieluebersicht';
            try {
                var eintraege = window.parent.document.querySelectorAll('.bh-nav-item');
                eintraege.forEach(function(el){
                    if (el.getAttribute('href') === hash) {
                        el.classList.add('active');
                    } else {
                        el.classList.remove('active');
                    }
                });
            } catch (e) {}
            aktiviereTabFuerHash(hash);
        }
        try {
            window.parent.addEventListener('hashchange', function(){ aktualisiereMenue(); });
        } catch (e) {}

        // Bei einem ECHTEN (neuen) Aufruf der Seite (frischer Tab oder F5-
        // Neuladen) soll die Navigation immer bei "Spielübersicht" starten -
        // auch wenn im Browser noch eine alte Sprungmarke (z.B. "#bh-
        // pressefragen") von einer frueheren Interaktion in der Adresse
        // steht. Streamlit fuehrt bei jedem Klick einen Rerun aus, OHNE die
        // Seite wirklich neu zu laden - das Flag auf "window.parent"
        // ueberlebt deshalb jeden Rerun, wird aber bei einem echten Neuladen
        // der Seite zurueckgesetzt. So laesst sich zuverlaessig zwischen
        // beidem unterscheiden.
        if (!window.parent.__bh_nav_initialisiert) {
            window.parent.__bh_nav_initialisiert = true;
            try {
                var neuerPfad = window.parent.location.pathname + window.parent.location.search + '#bh-spieluebersicht';
                window.parent.history.replaceState(null, '', neuerPfad);
            } catch (e) {}
            aktualisiereMenue('#bh-spieluebersicht');
        } else {
            aktualisiereMenue();
        }
    })();
    </script>
    """,
    height=0,
)

# ---------------------------------------------------------------------------
# Fusszeile
# ---------------------------------------------------------------------------
st.markdown(
    f"""
    <div style="margin-top: 40px; padding-top: 14px; border-top: 1px solid #333;
                text-align: center; font-size: 12px; color: #888;">
        {PRESSESPRECHER_NAME} &middot; {PRESSESPRECHER_TITEL} &middot; {UNSER_TEAM}
    </div>
    """,
    unsafe_allow_html=True,
)
