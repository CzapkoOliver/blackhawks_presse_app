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

Die Vereinsfarben (Schwarz, Rot, Weiss) werden ueber .streamlit/config.toml
gesetzt - diese Datei muss im selben Ordner wie app.py liegen (bzw. beim
Hochladen zu GitHub mit hochgeladen werden).

Start ueber das Terminal mit: streamlit run app.py
"""

from datetime import datetime

import streamlit as st

import spieldaten
import spielplan
import trainer_lookup
import fragen_generator
import live_uebersetzer

UNSER_TEAM = "EHF Passau Black Hawks"
PRESSESPRECHER_NAME = "Oliver Czapko"
PRESSESPRECHER_TITEL = "Stadion- und Pressesprecher"

# Feste Hoehe (in Pixeln) der beiden Spalten unten. Beide Spalten bekommen
# jeweils ihren EIGENEN Scrollbalken innerhalb dieser Hoehe - so kann man
# links durch lange Pressefragen scrollen, ohne dass rechts der laufende
# Live-Uebersetzer aus dem Blickfeld verschwindet (und umgekehrt). Bei Bedarf
# hier einfach die Zahl anpassen (z.B. kleiner auf einem kleineren Bildschirm).
SPALTEN_HOEHE = 820


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
# Kopfbereich: Vereinslogo-Emoji, Titel, fest hinterlegter Name/Funktion
# ---------------------------------------------------------------------------
st.markdown(
    """
    <div style="
        padding: 18px 20px;
        border-radius: 10px;
        background: linear-gradient(135deg, #000000 0%, #1a1a1a 100%);
        border: 1px solid #C8102E;
        margin-bottom: 18px;
    ">
        <div style="font-size: 26px; font-weight: 700; color: #ffffff; line-height: 1.3;">
            🏒 EHF Passau Black Hawks
        </div>
        <div style="font-size: 15px; color: #C8102E; font-weight: 600; margin-top: 2px;">
            Presse-Vorbereitung
        </div>
        <div style="font-size: 13px; color: #bbbbbb; margin-top: 10px;">
            Erstellt fuer <b style="color:#ffffff;">Oliver Czapko</b> &middot; Stadion- und Pressesprecher
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
    st.markdown("### 🎙️ Live-Übersetzer")
    with st.container(height=SPALTEN_HOEHE, border=True):
        st.caption("Läuft während der ganzen Pressekonferenz weiter, unabhängig von den Fragen links.")
        live_uebersetzer.render()

with spalte_haupt:
    st.markdown("### 📋 Spieldaten & Pressefragen")
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

            with st.spinner("Lade Spieldaten von DEB LIVE ..."):
                roher_text = spieldaten.hole_sichtbaren_text(url)
                daten = spieldaten.parse_spielbericht(roher_text)

            if not daten["heimteam"] or not daten["gastteam"] or not daten["endergebnis"]:
                st.error(
                    "Die Seite konnte nicht richtig ausgelesen werden. "
                    "Bitte pruefen, ob der Link stimmt und das Spiel bereits beendet ist."
                )
                st.stop()

            gegner = daten["gastteam"] if daten["heimteam"] == UNSER_TEAM else daten["heimteam"]

            with st.spinner("Lade Spielplan ..."):
                plan_text = spielplan.hole_sichtbaren_text(spielplan.SPIELPLAN_URL)
                alle_spiele = spielplan.parse_spielplan(plan_text)

            heute = datetime.now()
            naechste_unser_team = spielplan.naechste_spiele(alle_spiele, UNSER_TEAM, heute)
            naechste_gegner = spielplan.naechste_spiele(alle_spiele, gegner, heute)

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
                st.markdown("**Schuesse**")
                spalte1, spalte2 = st.columns(2)
                spalte1.metric(heim, daten["schuesse_heim"] if daten["schuesse_heim"] is not None else "-")
                spalte2.metric(gast, daten["schuesse_gast"] if daten["schuesse_gast"] is not None else "-")

                # ---- Zeile 2: Strafminuten ----
                st.markdown("**Strafminuten**")
                spalte3, spalte4 = st.columns(2)
                spalte3.metric(heim, daten["strafminuten_heim"] if daten["strafminuten_heim"] is not None else "-")
                spalte4.metric(gast, daten["strafminuten_gast"] if daten["strafminuten_gast"] is not None else "-")

                # ---- Zeile 3: Drittelergebnisse ----
                if daten["torfolge_pro_drittel"]:
                    st.markdown("**Drittelergebnisse**")
                    drittel_spalten = st.columns(len(daten["torfolge_pro_drittel"]))
                    for spalte, drittel in zip(drittel_spalten, sorted(daten["torfolge_pro_drittel"])):
                        heim_tore, gast_tore = daten["torfolge_pro_drittel"][drittel]
                        label = f"{drittel}. Drittel" if drittel <= 3 else "Verlaengerung"
                        spalte.metric(label, f"{heim_tore}:{gast_tore}")

            # ---- Offizielle & Trainer ----
            spalte_links, spalte_rechts = st.columns(2)

            with spalte_links:
                with st.container(border=True):
                    st.markdown("**🧑‍⚖️ Offizielle**")
                    st.write(f"Schiedsrichter: {daten['schiedsrichter'] or 'unbekannt'}")
                    st.write(f"Linienrichter: {daten['linienrichter'] or 'unbekannt'}")

            with spalte_rechts:
                with st.container(border=True):
                    st.markdown("**🧑‍💼 Trainer**")
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
                st.markdown("**📅 Naechste Spiele**")
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
            st.markdown("### 🎤 Pressekonferenz-Fragen")
            if st.button("Pressefragen generieren", type="primary"):
                with st.spinner("Claude analysiert das Spiel und formuliert Fragen ..."):
                    fragen = fragen_generator.generiere_pressefragen(
                        daten, heim_info, gast_info, naechste_unser_team, naechste_gegner
                    )
                st.session_state["fragen"] = fragen

            if "fragen" in st.session_state:
                with st.container(border=True):
                    st.markdown(st.session_state["fragen"])

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
