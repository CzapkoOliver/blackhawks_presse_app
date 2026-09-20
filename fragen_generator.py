"""
fragen_generator.py
---------------------
Nutzt die Claude API (Anthropic), um aus den Spieldaten sinnvolle
Pressekonferenz-Fragen fuer beide Trainer zu erzeugen. Fragen an einen
fremdsprachigen Trainer werden zusaetzlich auf Englisch ausgegeben.

Benoetigt eine Datei ".env" im selben Ordner mit der Zeile:
ANTHROPIC_API_KEY=dein-schluessel-hier
"""

import os

from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()

# Hinweis: Falls dieses Modell irgendwann nicht mehr verfuegbar ist, den
# aktuellen Modellnamen unter https://docs.claude.com/en/docs/about-claude/models
# nachschlagen und hier eintragen.
MODELL = "claude-opus-5"


def _baue_prompt(
    spieldaten: dict,
    heim_info: dict,
    gast_info: dict,
    naechste_heim: list,
    naechste_gast: list,
) -> str:
    def drittel_text(torfolge: dict | None) -> str:
        if not torfolge:
            return "nicht verfuegbar"
        teile = []
        for drittel in sorted(torfolge):
            heim_tore, gast_tore = torfolge[drittel]
            label = f"{drittel}. Drittel" if drittel <= 3 else "Verlaengerung"
            teile.append(f"{label} {heim_tore}:{gast_tore}")
        return ", ".join(teile)

    def spiele_text(spiele: list) -> str:
        if not spiele:
            return "keine Termine gefunden"
        return "; ".join(
            f"{s['datum'].strftime('%d.%m.%Y')} {s['heim']} vs {s['gast']}" for s in spiele
        )

    heim_braucht_englisch = heim_info["sprache"] not in ("Deutsch", "unbekannt")
    gast_braucht_englisch = gast_info["sprache"] not in ("Deutsch", "unbekannt")

    return f"""Du hilfst einem Pressesprecher eines Eishockey-Oberligisten bei der
Vorbereitung auf die Pressekonferenz nach dem Spiel.

SPIELDATEN:
- {spieldaten['heimteam']} {spieldaten['endergebnis']} {spieldaten['gastteam']}
- Zuschauer: {spieldaten['zuschauer']}
- Schuesse aufs Tor: {spieldaten['heimteam']} {spieldaten['schuesse_heim']} : {spieldaten['schuesse_gast']} {spieldaten['gastteam']}
- Strafminuten: {spieldaten['heimteam']} {spieldaten['strafminuten_heim']} : {spieldaten['strafminuten_gast']} {spieldaten['gastteam']}
- Torfolge pro Drittel (Heim:Gast): {drittel_text(spieldaten.get('torfolge_pro_drittel'))}
- Schiedsrichter: {spieldaten['schiedsrichter']}
- Trainer {spieldaten['heimteam']}: {spieldaten['trainer_heim']} ({heim_info['nationalitaet']})
- Trainer {spieldaten['gastteam']}: {spieldaten['trainer_gast']} ({gast_info['nationalitaet']})
- Naechste Spiele {spieldaten['heimteam']}: {spiele_text(naechste_heim)}
- Naechste Spiele {spieldaten['gastteam']}: {spiele_text(naechste_gast)}

AUFGABE:
Formuliere fuer JEDEN der beiden Trainer maximal 3 durchdachte, konkrete
Fragen (nicht mehr!) - getrennt fuer den Trainer von {spieldaten['heimteam']}
und den Trainer von {spieldaten['gastteam']}. Es MUESSEN immer beide
Abschnitte mit Fragen an BEIDE Trainer enthalten sein, auch wenn du dich
dafuer kurz fassen musst. Beziehe dich auf den tatsaechlichen Spielverlauf
(Ergebnis, Schussverhaeltnis, Strafminuten/Disziplin, knapp oder deutlich),
die Tabellensituation und die jeweils naechsten Gegner. Nutze die
Strafminuten z.B. fuer Fragen zu Disziplin, Special Teams (Powerplay/
Unterzahl) oder ob das Spiel emotional/haerter gefuehrt wurde. Achte
besonders auf die Torfolge pro Drittel - ein schwacher Start, ein
Umschwung nach einer Drittelpause oder ein spaeter Aufholversuch sind
oft ergiebiger fuer Fragen als nur das Endergebnis. Vermeide generische
Floskel-Fragen wie "Wie zufrieden sind Sie?".

FORMAT:
Gib die Antwort als zwei Abschnitte mit Markdown-Ueberschriften aus:
"## Fragen an den Trainer von {spieldaten['heimteam']}" und
"## Fragen an den Trainer von {spieldaten['gastteam']}", jeweils als
nummerierte Liste.
{"Da der Trainer von " + spieldaten['heimteam'] + " " + heim_info['sprache'] + " spricht, gib unter jeder deutschen Frage in Klammern direkt die englische Uebersetzung mit an." if heim_braucht_englisch else ""}
{"Da der Trainer von " + spieldaten['gastteam'] + " " + gast_info['sprache'] + " spricht, gib unter jeder deutschen Frage in Klammern direkt die englische Uebersetzung mit an." if gast_braucht_englisch else ""}
"""


def _hole_api_key() -> str | None:
    """
    Sucht den API-Schluessel an zwei moeglichen Stellen:
    - Lokal auf dem eigenen Rechner: in der Datei .env
    - Online auf Streamlit Community Cloud: in den dortigen "Secrets"
      (App-Einstellungen -> Secrets), abrufbar ueber st.secrets.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if api_key:
        return api_key
    try:
        import streamlit as st

        return st.secrets.get("ANTHROPIC_API_KEY")
    except Exception:
        return None


def generiere_pressefragen(
    spieldaten: dict,
    heim_info: dict,
    gast_info: dict,
    naechste_heim: list,
    naechste_gast: list,
) -> str:
    api_key = _hole_api_key()
    if not api_key:
        return (
            "Kein API-Schluessel gefunden. Lokal: in der Datei .env die Zeile "
            "ANTHROPIC_API_KEY=dein-schluessel eintragen. Online: in den "
            "Streamlit-Cloud-App-Einstellungen unter 'Secrets' hinterlegen."
        )

    client = Anthropic(api_key=api_key)
    prompt = _baue_prompt(spieldaten, heim_info, gast_info, naechste_heim, naechste_gast)

    antwort = client.messages.create(
        model=MODELL,
        # Grosszuegig bemessen, damit bei Modellen mit "Thinking"-Schritten
        # (die Zeichen vom selben Limit mitverbrauchen) trotzdem immer genug
        # Platz fuer BEIDE Trainer-Abschnitte bleibt und nichts abgeschnitten wird.
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )

    # Manche Modelle (z.B. mit "Thinking") liefern mehrere Bloecke zurueck,
    # z.B. erst einen Denk-Block und dann den eigentlichen Text-Block.
    # Wir suchen deshalb gezielt nach dem/den Text-Bloecken statt blind
    # den ersten Block zu nehmen.
    text_bloecke = [block.text for block in antwort.content if block.type == "text"]
    if not text_bloecke:
        return "Claude hat keine Textantwort geliefert (nur Denk-Schritte). Bitte nochmal versuchen."
    return "\n".join(text_bloecke)


if __name__ == "__main__":
    # Kleiner Test mit den echten Daten aus dem Riessersee-Spiel.
    beispiel_daten = {
        "heimteam": "SC Riessersee",
        "gastteam": "EHF Passau Black Hawks",
        "endergebnis": "4:2",
        "zuschauer": "1214",
        "schuesse_heim": 39,
        "schuesse_gast": 26,
        "strafminuten_heim": 13,
        "strafminuten_gast": 13,
        "torfolge_pro_drittel": {1: [3, 0], 2: [0, 1], 3: [1, 1]},
        "schiedsrichter": "ALTMANN Patrick / Zettl Michael",
        "trainer_heim": "CARLSSON LEIF",
        "trainer_gast": "REJA DANIEL",
    }
    beispiel_heim_info = {"nationalitaet": "Schweden", "sprache": "Englisch"}
    beispiel_gast_info = {"nationalitaet": "Kanada", "sprache": "Englisch"}

    print(
        generiere_pressefragen(
            beispiel_daten, beispiel_heim_info, beispiel_gast_info, [], []
        )
    )
