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
Hochladen zu GitHub mit hochgeladen werden).

Start ueber das Terminal mit: streamlit run app.py
"""

import time
from datetime import datetime

import streamlit as st

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

# Feste Hoehe (in Pixeln) der beiden Spalten unten. Beide Spalten bekommen
# jeweils ihren EIGENEN Scrollbalken innerhalb dieser Hoehe - so kann man
# links durch lange Pressefragen scrollen, ohne dass rechts der laufende
# Live-Uebersetzer aus dem Blickfeld verschwindet (und umgekehrt). Bei Bedarf
# hier einfach die Zahl anpassen (z.B. kleiner auf einem kleineren Bildschirm).
SPALTEN_HOEHE = 820

# Direkt nach Spielende dauert es auf DEB LIVE manchmal noch ein paar Minuten,
# bis die Seite den Spielstatus tatsaechlich auf "beendet" umstellt. Deshalb
# hier nicht sofort aufgeben, sondern automatisch ein paar Mal erneut
# versuchen, bevor eine Fehlermeldung kommt.
MAX_VERSUCHE = 5
WARTEZEIT_SEKUNDEN = 60


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


_playwright_browser_sicherstellen()

st.set_page_config(page_title="Black Hawks Presse-Vorbereitung", page_icon="🏒", layout="wide")

# ---------------------------------------------------------------------------
# Globales Erscheinungsbild: eigene Schriftarten (Space Grotesk fuer
# Ueberschriften/Zahlen, Inter fuer Fliesstext) sowie kleine Bausteine
# (Karten, Label) fuer die Stat-Kacheln weiter unten. Bewusst KEINE Eingriffe
# in Streamlits interne DOM-Struktur (z.B. Container-Raender) - das ist
# versionsabhaengig und bricht leicht. Nur eigene, selbst erzeugte HTML-
# Bloecke werden gestylt.
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
        font-weight: 700; font-size: 16px; color: #ffffff; margin: 4px 0 10px 0;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Kleine, wiederverwendbare Inline-Icons (statt Emoji) fuer die
# Abschnittsueberschriften - passend zum vorher abgestimmten Mockup.
BH_ICON_TRIKOT = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#C8102E" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="M7 15l4-6 3 3 5-8"/></svg>'
BH_ICON_MIKRO = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#C8102E" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v4M8 23h8"/></svg>'
BH_ICON_PFEIFE = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#C8102E" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="5"/><path d="M20 21a8 8 0 0 0-16 0"/></svg>'
BH_ICON_TRAINER = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#C8102E" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>'
BH_ICON_KALENDER = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#C8102E" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>'
BH_ICON_SPRECHBLASE = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#C8102E" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>'
BH_ICON_ZEITUNG = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#C8102E" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 22h16a2 2 0 0 0 2-2V4H8a2 2 0 0 0-2 2v14a2 2 0 0 1-2 2Zm0 0a2 2 0 0 1-2-2V9h4"/><path d="M18 14h-8M18 10h-8M12 18h-6"/></svg>'


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
        f'<div class="bh-value" style="font-size:24px; color:#ffffff; margin-top:4px;">{wert}</div></div>'
        for label, wert in karten
    )
    st.markdown(
        f'<div class="bh-card-grid" style="grid-template-columns: repeat({spalten}, minmax(0, 1fr));">{zellen}</div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Kopfbereich: Vereinslogo, Titel, fest hinterlegter Name/Funktion als Chip
# ---------------------------------------------------------------------------
st.markdown(
    """
    <div style="
        display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 14px;
        padding: 16px 22px;
        border-radius: 14px;
        background: linear-gradient(135deg, #000000 0%, #1a1a1a 100%);
        border-bottom: 2px solid #C8102E;
        margin-bottom: 22px;
    ">
        <div style="display:flex; align-items:center; gap:14px;">
            <div style="width:40px; height:40px; border-radius:10px; background:#C8102E;
                        display:flex; align-items:center; justify-content:center; flex-shrink:0;">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#ffffff" stroke-width="2"
                     stroke-linecap="round" stroke-linejoin="round">
                    <path d="M4 21l7-14 3 6h6l-9 8z"/><circle cx="19" cy="5" r="2"/>
                </svg>
            </div>
            <div>
                <div class="bh-value" style="font-size:20px; color:#ffffff; line-height:1.15;">
                    EHF PASSAU BLACK HAWKS
                </div>
                <div class="bh-label" style="color:#C8102E; margin-top:2px;">Presse-Vorbereitung</div>
            </div>
        </div>
        <div style="display:flex; align-items:center; gap:10px; padding:8px 16px; border-radius:999px;
                    background:#1a1a1a; border:1px solid #2e2e2e;">
            <div style="width:28px; height:28px; border-radius:50%; background:#2a2a2a;
                        display:flex; align-items:center; justify-content:center;">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#f5f5f5" stroke-width="2"
                     stroke-linecap="round" stroke-linejoin="round">
                    <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>
                </svg>
            </div>
            <div>
                <div style="font-size:13px; font-weight:600; color:#ffffff;">Oliver Czapko</div>
                <div style="font-size:11px; color:#9a9a9a;">Stadion- &amp; Pressesprecher</div>
            </div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Hauptbereich: Spieldaten & Pressefragen links, Live-Uebersetzer rechts.
# Beides steht dauerhaft nebeneinander auf derselben Seite (kein Reiter-
# Wechsel mehr). Jede der beiden Spalten steckt zusaetzlich in einer eigenen,
# hoehenbegrenzten Box mit eigenem Scrollbalken (st.container(height=...)):
# so lassen sich lange Pressefragen links durchscrollen, waehrend rechts der
# Live-Uebersetzer unveraendert sichtbar bleibt (und umgekehrt).
# ---------------------------------------------------------------------------
spalte_haupt, spalte_uebersetzer = st.columns([3, 2], gap="large")

with spalte_uebersetzer:
    bh_abschnitt_titel(BH_ICON_MIKRO, "Live-Übersetzer")
    with st.container(height=SPALTEN_HOEHE, border=True):
        st.caption("Läuft während der ganzen Pressekonferenz weiter, unabhängig von den Fragen links.")
        live_uebersetzer.render()

with spalte_haupt:
    bh_abschnitt_titel(BH_ICON_TRIKOT, "Spieldaten & Pressefragen")
    with st.container(height=SPALTEN_HOEHE, border=True):
        st.caption("Link zum DEB-LIVE-Spielbericht einfuegen und auf 'Daten laden' klicken.")

        url = st.text_input(
            "Link zum Spielbericht (aus der Browser-Adressleiste kopieren)",
            placeholder="https://deb-online.live/spielbericht/?gameId=...&divisionId=...",
        )

        laden = st.button("Daten laden", type="primary")

        if laden:
            if not url:
                st.warning("Bitte zuerst einen Link zum Spielbericht einfuegen.")
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
                    roher_text_spielverlauf, roher_text = spieldaten.hole_sichtbaren_text(url)
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

            # Alles in den Session-State speichern, damit es beim Klick auf den
            # zweiten Button ("Pressefragen generieren") nicht verloren geht.
            st.session_state["daten"] = daten
            st.session_state["gegner"] = gegner
            st.session_state["heim_info"] = heim_info
            st.session_state["gast_info"] = gast_info
            st.session_state["naechste_unser_team"] = naechste_unser_team
            st.session_state["naechste_gegner"] = naechste_gegner
            st.session_state.pop("fragen", None)  # alte Fragen verwerfen bei neuem Spiel

        if "daten" in st.session_state:
            daten = st.session_state["daten"]
            gegner = st.session_state["gegner"]
            heim_info = st.session_state["heim_info"]
            gast_info = st.session_state["gast_info"]
            naechste_unser_team = st.session_state["naechste_unser_team"]
            naechste_gegner = st.session_state["naechste_gegner"]

            heim = daten["heimteam"]
            gast = daten["gastteam"]

            st.divider()

            # ---- Kopfbereich: Endergebnis inkl. Zuschauerzahl ----
            if daten["zuschauer"]:
                try:
                    zuschauer_formatiert = f"{int(daten['zuschauer']):,}".replace(",", ".")
                except ValueError:
                    zuschauer_formatiert = daten["zuschauer"]
                zuschauer_text = f"vor {zuschauer_formatiert} Zuschauern"
            else:
                zuschauer_text = ""
            with st.container(border=True):
                st.markdown(
                    f"<div style='text-align:center; font-size:22px; font-weight:700;'>"
                    f"{heim} &ndash; {gast} &nbsp; <span style='color:#C8102E;'>{daten['endergebnis']}</span>"
                    f"</div>"
                    f"<div style='text-align:center; font-size:14px; color:#bbbbbb; margin-top:4px;'>"
                    f"{zuschauer_text.strip()}"
                    f"</div>",
                    unsafe_allow_html=True,
                )

                st.markdown("<div style='margin-top:18px;'></div>", unsafe_allow_html=True)

                # ---- Zeile 1: Schuesse ----
                st.markdown('<div class="bh-label" style="margin-bottom:8px;">Schuesse</div>', unsafe_allow_html=True)
                bh_karten_zeile(
                    [
                        (heim, daten["schuesse_heim"] if daten["schuesse_heim"] is not None else "-"),
                        (gast, daten["schuesse_gast"] if daten["schuesse_gast"] is not None else "-"),
                    ],
                    spalten=2,
                )

                # ---- Zeile 2: Strafminuten ----
                st.markdown('<div class="bh-label" style="margin:14px 0 8px;">Strafminuten</div>', unsafe_allow_html=True)
                bh_karten_zeile(
                    [
                        (heim, daten["strafminuten_heim"] if daten["strafminuten_heim"] is not None else "-"),
                        (gast, daten["strafminuten_gast"] if daten["strafminuten_gast"] is not None else "-"),
                    ],
                    spalten=2,
                )

                # ---- Zeile 3: Drittelergebnisse ----
                if daten["torfolge_pro_drittel"]:
                    st.markdown('<div class="bh-label" style="margin:14px 0 8px;">Drittelergebnisse</div>', unsafe_allow_html=True)
                    drittel_karten = []
                    for drittel in sorted(daten["torfolge_pro_drittel"]):
                        heim_tore, gast_tore = daten["torfolge_pro_drittel"][drittel]
                        label = f"{drittel}. Drittel" if drittel <= 3 else "Verlaengerung"
                        drittel_karten.append((label, f"{heim_tore}:{gast_tore}"))
                    bh_karten_zeile(drittel_karten, spalten=len(drittel_karten))

            # ---- Offizielle & Trainer ----
            spalte_links, spalte_rechts = st.columns(2)

            with spalte_links:
                with st.container(border=True):
                    bh_abschnitt_titel(BH_ICON_PFEIFE, "Offizielle")
                    st.write(f"Schiedsrichter: {daten['schiedsrichter'] or 'unbekannt'}")
                    st.write(f"Linienrichter: {daten['linienrichter'] or 'unbekannt'}")

            with spalte_rechts:
                with st.container(border=True):
                    bh_abschnitt_titel(BH_ICON_TRAINER, "Trainer")
                    st.write(
                        f"**{heim}:** {daten['trainer_heim'] or 'unbekannt'} "
                        f"({heim_info['nationalitaet']}, spricht {heim_info['sprache']})"
                    )
                    st.write(
                        f"**{gast}:** {daten['trainer_gast'] or 'unbekannt'} "
                        f"({gast_info['nationalitaet']}, spricht {gast_info['sprache']})"
                    )
                    if heim_info["nationalitaet"] == "unbekannt" or gast_info["nationalitaet"] == "unbekannt":
                        st.caption(
                            "Hinweis: Für einen der Trainer fehlt noch ein Eintrag in trainer.csv "
                            "(Nachschlagen z.B. über eliteprospects.com)."
                        )

            # ---- Naechste Spiele ----
            with st.container(border=True):
                bh_abschnitt_titel(BH_ICON_KALENDER, "Nächste Spiele")
                spalte_a, spalte_b = st.columns(2)
                with spalte_a:
                    st.write(f"**{UNSER_TEAM}**")
                    for s in naechste_unser_team:
                        st.write(f"- {s['datum'].strftime('%d.%m.%Y %H:%M')} — {s['heim']} vs {s['gast']} ({s['ort']})")
                with spalte_b:
                    st.write(f"**{gegner}**")
                    for s in naechste_gegner:
                        st.write(f"- {s['datum'].strftime('%d.%m.%Y %H:%M')} — {s['heim']} vs {s['gast']} ({s['ort']})")

            # ---- Pressefragen ----
            st.divider()
            bh_abschnitt_titel(BH_ICON_SPRECHBLASE, "Pressekonferenz-Fragen")
            if st.button("Pressefragen generieren", type="primary"):
                with st.spinner("Claude analysiert das Spiel und formuliert Fragen ..."):
                    fragen = fragen_generator.generiere_pressefragen(
                        daten, heim_info, gast_info, naechste_unser_team, naechste_gegner
                    )
                st.session_state["fragen"] = fragen

            if "fragen" in st.session_state:
                with st.container(border=True):
                    st.markdown(st.session_state["fragen"])

            # ---- Nachbericht ----
            st.divider()
            bh_abschnitt_titel(BH_ICON_ZEITUNG, "Nachbericht für die Presse")
            st.caption(
                "Erstellt aus den obigen Spieldaten einen druckfertigen Nachbericht "
                "(Headline, Text, O-Ton, Statistik). Die Live-Übersetzung läuft "
                "ausschließlich im Browser - die App weiß deshalb nicht automatisch, "
                "wer gerade spricht. Bitte die gewünschten, bereits übersetzten Zitate "
                "unten manuell aus dem Live-Übersetzer-Verlauf (links kopieren, siehe "
                "Textfeld 'Transkript als Text') in das passende Feld einfügen. Leer "
                "gelassene Felder werden im O-Ton-Abschnitt als noch zu ergänzen "
                "markiert - Claude erfindet keine Aussagen."
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
