"""
nachbericht_generator.py
--------------------------
Erstellt aus den Spieldaten (und optional den bereits ins Deutsche
uebersetzten Pressekonferenz-Zitaten aus live_uebersetzer.py) einen
druckfertigen Nachbericht fuer die Presse - im gewohnten Format:
Sperrfrist, Headline, Fliesstext mit den wichtigsten Entwicklungen,
O-Ton, Statistik.

WICHTIG zu den Zitaten (O-Ton):
Die Live-Uebersetzung laeuft komplett im Browser (siehe live_uebersetzer.py)
und die App weiss NICHT automatisch, wer im jeweiligen Moment spricht.
Deshalb werden hier bewusst KEINE Zitate von Claude erfunden oder
Personen zugeordnet - stattdessen kopiert der Nutzer die gewuenschten,
bereits uebersetzten Saetze selbst aus dem Live-Uebersetzer-Transkript
in das Zitate-Feld (Format "Name: Zitat" pro Zeile). Nur diese vom
Nutzer bereitgestellten Zitate werden fuer den O-Ton-Abschnitt verwendet.

Benoetigt eine Datei ".env" im selben Ordner mit der Zeile:
ANTHROPIC_API_KEY=dein-schluessel-hier
"""

import difflib
import os
import re

from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()

# Fuer einen gut geschriebenen, journalistischen Fliesstext wird bewusst
# dasselbe hochwertige Modell wie beim Pressefragen-Generator verwendet.
MODELL = "claude-opus-5"


def _drittel_text(torfolge: dict | None) -> str:
    if not torfolge:
        return "nicht verfuegbar"
    teile = []
    for drittel in sorted(torfolge):
        heim_tore, gast_tore = torfolge[drittel]
        label = f"{drittel}. Drittel" if drittel <= 3 else "Verlaengerung"
        teile.append(f"{label} {heim_tore}:{gast_tore}")
    return ", ".join(teile)


def _tore_text(tore_liste: list | None) -> str:
    if not tore_liste:
        return "nicht verfuegbar"
    zeilen = []
    for tor in tore_liste:
        # Bevorzugt den sauber herausgeloesten Torschuetzen-Namen (z.B.
        # "Grady Hobbs") statt des rohen Seitentexts - das reduziert das
        # Risiko, dass Claude beim Formulieren einen Vornamen vertauscht.
        if tor.get("torschuetze"):
            info = f" - {tor['torschuetze']}"
        elif tor.get("info"):
            info = f" - {tor['info']}"
        else:
            info = ""
        zeilen.append(f"{tor['stand']} ({tor['zeit']}, {tor['drittel']}. Drittel){info}")
    return "; ".join(zeilen)


def _ist_wahrscheinlich_verwechselter_vorname(geschriebener_vorname: str, korrekter_vorname: str) -> bool:
    """
    Entscheidet, ob ein von Claude geschriebenes Wort vor einem bekannten
    Nachnamen wahrscheinlich ein FALSCH GESCHRIEBENER/VERWECHSELTER Vorname
    ist (z.B. "Grant" statt "Grady") - im Unterschied zu einem normalen
    (im Deutschen grossgeschriebenen) Substantiv davor wie "Torschuetze"
    oder "Stuermer". Dafuer wird geprueft, ob sich die beiden Woerter
    aehnlich genug sind (typischer Tippfehler/Verwechslung), statt jedes
    grossgeschriebene Wort vor dem Nachnamen blind zu ersetzen.
    """
    if geschriebener_vorname == korrekter_vorname:
        return False
    if len(geschriebener_vorname) < 3:
        return False
    aehnlichkeit = difflib.SequenceMatcher(
        None, geschriebener_vorname.lower(), korrekter_vorname.lower()
    ).ratio()
    return aehnlichkeit >= 0.5


def _korrigiere_torschuetzen_namen(text: str, spieldaten: dict) -> str:
    """
    Sicherheitsnetz GEGEN von Claude beim freien Formulieren versehentlich
    vertauschte oder abgekuerzte Vornamen. Ersetzt jede Stelle, an der ein
    bekannter Spieler-Nachname mit einem verdaechtig aehnlichen (aber
    falschen) oder abgekuerzten Vornamen auftaucht, durch die korrekte
    Schreibweise aus den echten Spieldaten - unabhaengig davon, was Claude
    geschrieben hat.

    Bekannte Namen kommen aus zwei Quellen: dem umfassenden Namens-
    verzeichnis "spieler_namen" (aus Spielverlauf + Spielbericht, deckt
    ALLE im Spiel erwaehnten Spieler ab - nicht nur Torschuetzen) sowie,
    als Rueckfallebene fuer aeltere Aufrufe ohne dieses Verzeichnis, den
    Torschuetzen aus "tore_liste".
    """
    bekannte_namen: dict[str, str] = {}
    for tor in (spieldaten.get("tore_liste") or []):
        torschuetze = tor.get("torschuetze")
        if torschuetze and " " in torschuetze:
            vorname, nachname = torschuetze.rsplit(" ", 1)
            bekannte_namen.setdefault(nachname, vorname)
    # Das umfassende Verzeichnis (falls vorhanden) hat Vorrang, da es auf
    # mehr Erwaehnungen basiert und damit zuverlaessiger ist.
    bekannte_namen.update(spieldaten.get("spieler_namen") or {})

    for nachname, korrekter_vorname in bekannte_namen.items():
        nachname_escaped = re.escape(nachname)

        def _ersetzen(treffer: re.Match) -> str:
            geschriebener_vorname = treffer.group(1)
            if _ist_wahrscheinlich_verwechselter_vorname(geschriebener_vorname, korrekter_vorname):
                return f"{korrekter_vorname} {nachname}"
            return treffer.group(0)

        muster = rf"\b([A-ZÀ-Ö][A-Za-zÀ-ÖØ-öø-ÿ'\-]*)\s+{nachname_escaped}\b"
        text = re.sub(muster, _ersetzen, text)

        # Zusaetzliches Muster: abgekuerzte Vornamen ("G. Hobbs", "L Mössinger")
        # werden IMMER auf den vollen Namen ausgeschrieben, unabhaengig davon,
        # ob der Anfangsbuchstabe zufaellig passt - der Nutzer moechte
        # ausdruecklich ausgeschriebene Vornamen im Nachbericht sehen.
        abkuerzung_muster = rf"\b[A-ZÀ-Ö]\.?\s+{nachname_escaped}\b"
        text = re.sub(abkuerzung_muster, f"{korrekter_vorname} {nachname}", text)

    return text


def _baue_prompt(
    spieldaten: dict,
    heim_info: dict,
    gast_info: dict,
    zitate_text: str,
    sperrfrist: str,
) -> str:
    zitate_hinweis = (
        f"Folgende, bereits vom Nutzer ausgewaehlte und ins Deutsche uebersetzte "
        f"Original-Zitate aus der Pressekonferenz sollen im O-Ton-Abschnitt "
        f"verwendet werden (Format ist 'Name: Zitat' je Zeile):\n{zitate_text.strip()}"
        if zitate_text.strip()
        else "Es wurden diesmal KEINE Zitate uebergeben."
    )

    return f"""Du bist ein erfahrener Pressesprecher eines deutschen Eishockey-
Oberligisten und schreibst einen Nachbericht fuer die Presse direkt nach dem Spiel.

SPIELDATEN:
- {spieldaten['heimteam']} {spieldaten['endergebnis']} {spieldaten['gastteam']}
- Zuschauer: {spieldaten['zuschauer']}
- Schuesse aufs Tor: {spieldaten['heimteam']} {spieldaten['schuesse_heim']} : {spieldaten['schuesse_gast']} {spieldaten['gastteam']}
- Strafminuten: {spieldaten['heimteam']} {spieldaten['strafminuten_heim']} : {spieldaten['strafminuten_gast']} {spieldaten['gastteam']}
- Torfolge pro Drittel (Heim:Gast): {_drittel_text(spieldaten.get('torfolge_pro_drittel'))}
- Torchronologie: {_tore_text(spieldaten.get('tore_liste'))}
- Schiedsrichter: {spieldaten['schiedsrichter']}
- Linienrichter: {spieldaten['linienrichter']}
- Trainer {spieldaten['heimteam']}: {spieldaten['trainer_heim']} ({heim_info['nationalitaet']})
- Trainer {spieldaten['gastteam']}: {spieldaten['trainer_gast']} ({gast_info['nationalitaet']})

ZITATE (O-Ton):
{zitate_hinweis}

AUFGABE:
Schreibe einen professionellen, druckfertigen Nachbericht nach klassischem
Sportjournalismus-Stil (aehnlich einer dpa-Spielzusammenfassung). Beziehe
dich ausschliesslich auf die oben angegebenen echten Spieldaten - erfinde
KEINE zusaetzlichen Spielsituationen, Torschuetzen oder Ereignisse, die
nicht aus den Daten hervorgehen. Uebernimm ALLE Spieler- und Trainernamen
EXAKT buchstabengetreu aus der Torchronologie bzw. den Trainerangaben oben -
NIEMALS einen Vornamen aendern, "korrigieren" oder durch einen aehnlich
klingenden, gebraeuchlicheren Namen ersetzen (Beispiel: Steht "Grady Hobbs"
in der Torchronologie, schreibe IMMER "Grady Hobbs" - niemals "Grant Hobbs"
oder eine andere Variante). Schreibe den Vornamen JEDES Mal VOLLSTAENDIG
aus, wenn ein Spieler oder Trainer im Fliesstext genannt wird - VERWENDE
NIEMALS Abkuerzungen wie "G. Hobbs" oder nur den Nachnamen allein, auch
nicht bei Wiederholungen oder um Wiederholungen zu vermeiden. Gehe im
Fliesstext insbesondere auf den
Spielverlauf ein (starker/schwacher Start, Wendepunkte zwischen den
Dritteln, spannende Schlussphase falls das Ergebnis knapp war oder wurde,
Schussverhaeltnis, Disziplin/Strafminuten falls auffaellig).

Falls oben unter "ZITATE" tatsaechlich Zitate uebergeben wurden: Nutze
zusaetzlich deren INHALTLICHE Aussage (z.B. Einschaetzung zum Spielverlauf,
zu einzelnen Phasen, zur eigenen oder gegnerischen Leistung), um die
Fliesstext-Absaetze realistischer und einordnender zu schreiben - so wie es
ein Reporter tut, der die Pressekonferenz tatsaechlich gehoert hat. Verwende
dabei im Fliesstext NICHT den woertlichen Zitat-Text selbst (der bleibt dem
O-Ton-Abschnitt vorbehalten, siehe Regel unten), sondern nur die Einordnung/
Bewertung, die daraus hervorgeht (z.B. "Coach XY fuehrte den Sieg auf ...
zurueck" statt das Zitat zu wiederholen). Wurden KEINE Zitate uebergeben,
schreibe den Fliesstext wie gewohnt ausschliesslich anhand der Spieldaten -
das ist ein voellig normaler, gueltiger Fall und kein Mangel.

Fuer den O-Ton-Abschnitt gilt eine STRENGE Regel: Verwende AUSSCHLIESSLICH
die oben unter "ZITATE" aufgefuehrten, vom Nutzer bereitgestellten Zitate -
wortwoertlich oder nur leicht sprachlich geglaettet, aber inhaltlich
unveraendert und mit der jeweils angegebenen Namenszuordnung. Erfinde
NIEMALS eigene Zitate oder ordne eine Aussage einer Person zu, fuer die
kein Zitat uebergeben wurde. Falls keine Zitate uebergeben wurden, schreibe
im O-Ton-Abschnitt stattdessen woertlich: "Noch keine Zitate erfasst - bitte
Original-Aussagen aus dem Live-Uebersetzer-Transkript ergaenzen." und
erfinde nichts.

FORMAT (genau in dieser Reihenfolge, als Markdown):
1. Eine Zeile "Sperrfrist bis: {sperrfrist or 'keine'}"
2. Eine kurze, reisserische Vorzeile (Kicker) als "**<Vorzeile>**" (z.B. Ergebnis-
   Einordnung wie "Heimsieg mit Nervenkitzel:"), danach in der naechsten Zeile
   die Haupt-Headline als "# <Headline>" (z.B. "Black Hawks schlagen {spieldaten['gastteam']} {spieldaten['endergebnis']}").
3. 3-5 Fliesstext-Absaetze mit den wichtigsten Entwicklungen des Spiels.
4. Abschnitt "## O-Ton" mit den Zitaten (siehe Regel oben), jeweils als
   eigener Absatz im Format "**Name:** \"Zitat\"".
5. Abschnitt "## Statistik" mit GENAU diesen Zeilen, jede als eigener Absatz
   und IN DIESER REIHENFOLGE (keine zusaetzlichen Zeilen dazwischen):
   - "**{spieldaten['heimteam']} -- {spieldaten['gastteam']}**" (fett)
   - "Tore: " gefolgt von jedem Tor als "Spielstand Torschuetze (Minute)",
     getrennt durch "; " (z.B. "1:0 Leonard Mössinger (5.); 2:0 Grady Hobbs (19.)"),
     nur falls die Torchronologie oben verfuegbar ist - sonst diese Zeile weglassen.
   - "Zuschauer: {spieldaten['zuschauer']}"
   - "Schiedsrichter: {spieldaten['schiedsrichter']}"
   - "Linienrichter: {spieldaten['linienrichter']}" (nur falls vorhanden)

Schreibe auf Deutsch, sachlich-professionell, keine Emojis.
"""


def _hole_api_key() -> str | None:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if api_key:
        return api_key
    try:
        import streamlit as st

        return st.secrets.get("ANTHROPIC_API_KEY")
    except Exception:
        return None


def generiere_nachbericht(
    spieldaten: dict,
    heim_info: dict,
    gast_info: dict,
    zitate_text: str = "",
    sperrfrist: str = "keine",
) -> str:
    api_key = _hole_api_key()
    if not api_key:
        return (
            "Kein API-Schluessel gefunden. Lokal: in der Datei .env die Zeile "
            "ANTHROPIC_API_KEY=dein-schluessel eintragen. Online: in den "
            "Streamlit-Cloud-App-Einstellungen unter 'Secrets' hinterlegen."
        )

    client = Anthropic(api_key=api_key)
    prompt = _baue_prompt(spieldaten, heim_info, gast_info, zitate_text, sperrfrist)

    antwort = client.messages.create(
        model=MODELL,
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )

    text_bloecke = [block.text for block in antwort.content if block.type == "text"]
    if not text_bloecke:
        return "Claude hat keine Textantwort geliefert (nur Denk-Schritte). Bitte nochmal versuchen."

    nachbericht_text = "\n".join(text_bloecke)
    # Sicherheitsnetz: falls trotz der Anweisung im Prompt doch ein Vorname
    # vertauscht wurde, hier automatisch auf die korrekte Schreibweise aus
    # den echten Spieldaten zuruecksetzen.
    nachbericht_text = _korrigiere_torschuetzen_namen(nachbericht_text, spieldaten)
    return nachbericht_text


if __name__ == "__main__":
    beispiel_daten = {
        "heimteam": "Passau Black Hawks",
        "gastteam": "Höchstadter EC",
        "endergebnis": "8:5",
        "zuschauer": "690",
        "schuesse_heim": 42,
        "schuesse_gast": 44,
        "strafminuten_heim": 14,
        "strafminuten_gast": 10,
        "torfolge_pro_drittel": {1: [2, 0], 2: [3, 2], 3: [3, 3]},
        "tore_liste": [
            {"drittel": 1, "zeit": "05:00", "stand": "1:0", "info": "Leonard Mössinger"},
            {"drittel": 1, "zeit": "19:00", "stand": "2:0", "info": "Grady Hobbs"},
        ],
        "schiedsrichter": "Wohlgemuth / Harrer",
        "linienrichter": "Hintermeier / Ohlwein",
        "trainer_heim": "Daniel Reja",
        "trainer_gast": "Morgan Persson",
    }
    beispiel_heim_info = {"nationalitaet": "Kanada", "sprache": "Englisch"}
    beispiel_gast_info = {"nationalitaet": "Schweden", "sprache": "Englisch"}
    beispiel_zitate = "Daniel Reja: Wir muessen einfacheres Eishockey spielen."

    print(generiere_nachbericht(beispiel_daten, beispiel_heim_info, beispiel_gast_info, beispiel_zitate))
