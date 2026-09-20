"""
app.py
------
Die Streamlit-Oberflaeche der Presse-Vorbereitungs-App fuer die Passau Black Hawks.

Fuehrt alle Bausteine zusammen:
- spieldaten.py      -> Endergebnis, Zuschauer, Schiedsrichter, Schuesse, Trainer
- spielplan.py       -> naechste zwei Spiele beider Mannschaften
- trainer_lookup.py  -> Nationalitaet/Sprache der Trainer
- fragen_generator.py -> Pressekonferenz-Fragen per Claude API (zweisprachig bei Bedarf)

Start ueber das Terminal mit: streamlit run app.py
"""

from datetime import datetime

import streamlit as st

import spieldaten
import spielplan
import trainer_lookup
import fragen_generator

UNSER_TEAM = "EHF Passau Black Hawks"


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

st.set_page_config(page_title="Black Hawks Presse-Vorbereitung", page_icon="🏒", layout="centered")
st.title("🏒 Presse-Vorbereitung: Passau Black Hawks")
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

    # ---- Kopfbereich: Endergebnis ----
    st.header(f"{heim}  {daten['endergebnis']}  {gast}")

    spalte1, spalte2, spalte3 = st.columns(3)
    spalte1.metric("Zuschauer", daten["zuschauer"] or "unbekannt")
    spalte2.metric(f"Schuesse {heim}", daten["schuesse_heim"] if daten["schuesse_heim"] is not None else "-")
    spalte3.metric(f"Schuesse {gast}", daten["schuesse_gast"] if daten["schuesse_gast"] is not None else "-")

    spalte4, spalte5 = st.columns(2)
    spalte4.metric(f"Strafminuten {heim}", daten["strafminuten_heim"] if daten["strafminuten_heim"] is not None else "-")
    spalte5.metric(f"Strafminuten {gast}", daten["strafminuten_gast"] if daten["strafminuten_gast"] is not None else "-")

    # ---- Drittelergebnisse ----
    if daten["torfolge_pro_drittel"]:
        st.subheader("Drittelergebnisse")
        for drittel in sorted(daten["torfolge_pro_drittel"]):
            heim_tore, gast_tore = daten["torfolge_pro_drittel"][drittel]
            label = f"{drittel}. Drittel" if drittel <= 3 else "Verlaengerung"
            st.write(f"**{label}:** {heim_tore}:{gast_tore}")

    # ---- Offizielle ----
    st.subheader("Offizielle")
    st.write(f"**Schiedsrichter:** {daten['schiedsrichter'] or 'unbekannt'}")
    st.write(f"**Linienrichter:** {daten['linienrichter'] or 'unbekannt'}")

    # ---- Trainer ----
    st.subheader("Trainer")
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
    st.subheader("Naechste Spiele")
    st.write(f"**{UNSER_TEAM}:**")
    for s in naechste_unser_team:
        st.write(f"- {s['datum'].strftime('%d.%m.%Y %H:%M')} — {s['heim']} vs {s['gast']} ({s['ort']})")

    st.write(f"**{gegner}:**")
    for s in naechste_gegner:
        st.write(f"- {s['datum'].strftime('%d.%m.%Y %H:%M')} — {s['heim']} vs {s['gast']} ({s['ort']})")

    # ---- Pressefragen ----
    st.subheader("Pressekonferenz-Fragen")
    if st.button("Pressefragen generieren"):
        with st.spinner("Claude analysiert das Spiel und formuliert Fragen ..."):
            fragen = fragen_generator.generiere_pressefragen(
                daten, heim_info, gast_info, naechste_unser_team, naechste_gegner
            )
        st.session_state["fragen"] = fragen

    if "fragen" in st.session_state:
        st.markdown(st.session_state["fragen"])
