"""
nachbericht_generator.py
--------------------------
Erstellt aus den Spieldaten (und optional den bereits ins Deutsche
uebersetzten Pressekonferenz-Zitaten aus live_uebersetzer.py) einen
druckfertigen Nachbericht fuer die Presse - im gewohnten Format:
Sperrfrist, Headline, Fliesstext mit den wichtigsten Entwicklungen,
Fliesstext (mit eingebauten O-Toenen), Statistik am Ende.

WICHTIG zu den Zitaten (O-Ton):
Die Live-Uebersetzung laeuft komplett im Browser (siehe live_uebersetzer.py)
und die App weiss NICHT automatisch, wer im jeweiligen Moment spricht.
Deshalb werden hier bewusst KEINE Zitate von Claude erfunden oder
Personen zugeordnet - stattdessen kopiert der Nutzer die gewuenschten,
bereits uebersetzten Saetze selbst aus dem Live-Uebersetzer-Transkript
in das Zitate-Feld (Format "Name: Zitat" pro Zeile). Nur diese vom
Nutzer bereitgestellten Zitate werden in den Fliesstext eingebaut.

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


def _minute(zeit: str) -> str:
    """"05:03" -> "6." (Tor faellt in der 6. Spielminute, wie im Eishockey ueblich)."""
    try:
        minuten = int(zeit.split(":")[0])
        return f"{minuten + 1}."
    except Exception:
        return zeit


def _tore_text(tore_liste: list | None, heimteam: str = "Heim", gastteam: str = "Gast") -> str:
    if not tore_liste:
        return "nicht verfuegbar"
    zeilen = []
    for tor in tore_liste:
        # Bevorzugt den sauber aufgeloesten Torschuetzen-Namen (z.B.
        # "Grady Hobbs") statt des rohen Seitentexts - das reduziert das
        # Risiko, dass Claude beim Formulieren einen Vornamen vertauscht.
        if tor.get("torschuetze"):
            team = heimteam if tor.get("team") == "heim" else gastteam if tor.get("team") == "gast" else ""
            info = f" - {tor['torschuetze']}"
            if team:
                info += f" ({team})"
            if tor.get("spielart") and tor["spielart"] != "EQ":
                info += f" [{tor['spielart']}]"
            if tor.get("assists"):
                info += f", Vorlagen: {', '.join(tor['assists'])}"
        elif tor.get("info"):
            info = f" - {tor['info']}"
        else:
            info = ""
        zeilen.append(f"{tor['stand']} ({_minute(tor['zeit'])} Minute, {tor['drittel']}. Drittel){info}")
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
        # WICHTIG: Claude uebernimmt Nachnamen haeufig genau so, wie sie in
        # den Quelldaten standen - und die DEB-LIVE-Kaderliste/Torschuetzen-
        # liste zeigt Nachnamen durchgehend GROSSGESCHRIEBEN (z.B. "MACKINNON"
        # statt "Mackinnon", wie es im eigenen Namensverzeichnis hinterlegt
        # ist). Ohne Gross-/Kleinschreibung zu ignorieren, wuerde die
        # Korrektur solche Faelle schlicht nicht finden - deshalb ueberall
        # re.IGNORECASE verwenden und die korrekte Schreibweise (nachname,
        # korrekter_vorname) beim Ersetzen fest vorgeben.

        def _ersetzen(treffer: re.Match) -> str:
            geschriebener_vorname = treffer.group(1)
            if _ist_wahrscheinlich_verwechselter_vorname(geschriebener_vorname, korrekter_vorname):
                return f"{korrekter_vorname} {nachname}"
            return treffer.group(0)

        # Fall 1: "Vorname Nachname" (uebliche Reihenfolge im Fliesstext) -
        # wird nur ersetzt, wenn der geschriebene Vorname dem korrekten
        # Vornamen aehnlich genug ist (Verwechslungs-Schutz, siehe oben).
        muster = rf"\b([A-ZÀ-Ö][A-Za-zÀ-ÖØ-öø-ÿ'\-]*)\s+{nachname_escaped}\b"
        text = re.sub(muster, _ersetzen, text, flags=re.IGNORECASE)

        # Fall 2: abgekuerzter Vorname VOR dem Nachnamen ("G. Hobbs") - wird
        # IMMER auf den vollen Namen ausgeschrieben, unabhaengig davon, ob
        # der Anfangsbuchstabe zufaellig passt - volle Vornamen sind Pflicht.
        abkuerzung_muster_davor = rf"\b[A-ZÀ-Ö]\.?\s+{nachname_escaped}\b"
        text = re.sub(abkuerzung_muster_davor, f"{korrekter_vorname} {nachname}", text, flags=re.IGNORECASE)

        # Fall 3: abgekuerzter Vorname NACH dem Nachnamen ("MACKINNON J.",
        # "HOBBS G.") - die Reihenfolge, wie sie in der DEB-LIVE-Torschuetzen-
        # liste selbst verwendet wird und daher von Claude gelegentlich direkt
        # uebernommen wird. Wird auf "Vorname Nachname" normalisiert, damit
        # im Fliesstext durchgaengig die ausgeschriebene Form steht.
        abkuerzung_muster_danach = rf"\b{nachname_escaped}\s+[A-ZÀ-Ö]\.?(?!\w)"
        text = re.sub(abkuerzung_muster_danach, f"{korrekter_vorname} {nachname}", text, flags=re.IGNORECASE)

    return text


def _baue_prompt(
    spieldaten: dict,
    heim_info: dict,
    gast_info: dict,
    zitate_text: str,
    sperrfrist: str,
) -> str:
    zitate_hinweis = (
        "Folgende, bereits vom Nutzer ausgewaehlte und ins Deutsche uebersetzte "
        "Original-Zitate aus der Pressekonferenz stehen zur Verfuegung "
        f"(Format ist 'Name: Zitat' je Zeile):\n{zitate_text.strip()}"
        if zitate_text.strip()
        else "Es wurden diesmal KEINE Zitate uebergeben."
    )

    anpfiff = spieldaten.get("anpfiff_uhrzeit")
    anpfiff_zeile = f"- Anpfiff: {anpfiff} Uhr\n" if anpfiff else ""

    return f"""Du bist ein langjaehriger Sportredakteur mit sehr grosser Erfahrung im
Eishockey (Oberliga, DEL2, DEL, internationale Turniere). Du kennst das Spiel,
seine Taktik und seine Sprache, schreibst praezise, lebendig und fundiert und
hast einen sicheren Blick fuer Wendepunkte und Spielcharakter. Du schreibst
den Nachbericht zu einem Heimspiel der EHF Passau Black Hawks. Der Text muss
sowohl auf der Vereinswebsite und in den Vereinskanaelen als auch von der
Tagespresse unveraendert druckbar sein: sachlich fair gegenueber dem Gegner,
mit erkennbarer Naehe zum Heimteam, ohne Floskelkitsch und ohne Polemik.

SPIELDATEN:
- {spieldaten['heimteam']} {spieldaten['endergebnis']} {spieldaten['gastteam']}
{anpfiff_zeile}- Zuschauer: {spieldaten['zuschauer']}
- Schuesse aufs Tor: {spieldaten['heimteam']} {spieldaten['schuesse_heim']} : {spieldaten['schuesse_gast']} {spieldaten['gastteam']}
- Strafminuten: {spieldaten['heimteam']} {spieldaten['strafminuten_heim']} : {spieldaten['strafminuten_gast']} {spieldaten['gastteam']}
- Torfolge pro Drittel (Heim:Gast): {_drittel_text(spieldaten.get('torfolge_pro_drittel'))}
- Torchronologie: {_tore_text(spieldaten.get('tore_liste'), spieldaten['heimteam'], spieldaten['gastteam'])}
- Schiedsrichter: {spieldaten['schiedsrichter']}
- Linienrichter: {spieldaten['linienrichter']}
- Trainer {spieldaten['heimteam']}: {spieldaten.get('trainer_heim_name') or spieldaten['trainer_heim']} ({heim_info['nationalitaet']})
- Trainer {spieldaten['gastteam']}: {spieldaten.get('trainer_gast_name') or spieldaten['trainer_gast']} ({gast_info['nationalitaet']})

ZITATE (O-Toene):
{zitate_hinweis}

AUFGABE:
Schreibe einen druckfertigen Spielbericht im Stil eines erfahrenen
Sportredakteurs. Beziehe dich ausschliesslich auf die oben angegebenen echten
Daten - erfinde KEINE Spielsituationen, Torschuetzen, Vorlagen, Strafen oder
sonstigen Ereignisse, die nicht aus den Daten hervorgehen. Deute den
Spielverlauf aus den Daten (Start, Wendepunkte zwischen den Dritteln,
Schlussphase, Schussverhaeltnis, Disziplin/Strafminuten) und ordne ihn
fachkundig ein, ohne dabei Details zu behaupten, die die Daten nicht belegen.

NAMEN: Uebernimm ALLE Spieler- und Trainernamen EXAKT buchstabengetreu aus der
Torchronologie bzw. den Trainerangaben - NIEMALS einen Vornamen aendern,
"korrigieren" oder durch einen aehnlich klingenden Namen ersetzen (Steht
"Grady Hobbs" da, schreibe IMMER "Grady Hobbs", nie "Grant Hobbs"). Schreibe
bei JEDER Nennung den Vornamen VOLLSTAENDIG aus; niemals Abkuerzungen wie
"G. Hobbs" und niemals den Nachnamen allein, auch nicht bei Wiederholungen.
Variiere stattdessen mit Formulierungen wie "der Stuermer", "der Torschuetze",
"der Kapitaen" nur, wenn die Daten diese Funktion belegen.

O-TOENE IM FLIESSTEXT: Falls oben Zitate uebergeben wurden, baue sie direkt in
den Fliesstext ein, dort wo sie inhaltlich passen (z.B. die Trainereinschaetzung
zur Entscheidung im Mitteldrittel am Ende des entsprechenden Absatzes oder
zum Schluss). Wie in einem Zeitungsbericht: woertliches Zitat in
Anfuehrungszeichen, mit Namen und Funktion des Sprechers (z.B. Trainer des
Gegners), sauber in den Satz eingebettet ("..., sagte Trainer Vorname
Nachname." oder "'...', betonte ..."). Verwende AUSSCHLIESSLICH die
uebergebenen Zitate - woertlich oder nur leicht sprachlich geglaettet, inhaltlich
unveraendert und mit der angegebenen Namenszuordnung. Erfinde NIEMALS Zitate,
Paraphrasen in Anfuehrungszeichen oder Aussagen von Personen, fuer die kein Zitat
uebergeben wurde. Es gibt KEINEN separaten O-Ton-Abschnitt. Wurden keine Zitate
uebergeben, schreibe den Bericht ausschliesslich aus den Spieldaten; das ist ein
normaler Fall - weise im Text nicht darauf hin und fuege keinen Platzhalter ein.

FORMAT (genau in dieser Reihenfolge, als Markdown):
1. Eine Zeile "Sperrfrist bis: {sperrfrist or 'keine'}"
2. Eine kurze Vorzeile (Kicker) als "**<Vorzeile>**" (z.B. eine Ergebnis-
   Einordnung wie "Heimsieg mit Nervenkitzel:"), danach in der naechsten Zeile
   die Haupt-Headline als "# <Headline>" (z.B. "Black Hawks schlagen {spieldaten['gastteam']} {spieldaten['endergebnis']}").
3. 4-6 Fliesstext-Absaetze: ein Einstieg (Lead) mit Ergebnis und Kernaussage,
   dann der Spielverlauf Drittel fuer Drittel, die Entscheidung, am Ende
   Ausblick oder Fazit. Die O-Toene (falls vorhanden) sind hierin integriert.
4. Abschnitt "## Statistik" mit GENAU diesen Zeilen, jede als eigener Absatz
   und IN DIESER REIHENFOLGE (keine zusaetzlichen Zeilen dazwischen):
   - "**{spieldaten['heimteam']} -- {spieldaten['gastteam']}**" (fett)
   - "Tore: " gefolgt von jedem Tor als "Spielstand Torschuetze (Minute)",
     getrennt durch "; " (z.B. "1:0 Leonard Mössinger (5.); 2:0 Grady Hobbs (19.)" - die Minute
     steht in der Torchronologie oben bereits fertig berechnet),
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

    # Haeufiger Fehler beim Einfuegen in die Streamlit-Secrets: Leerzeichen,
    # Zeilenumbruch oder Anfuehrungszeichen um den Schluessel herum.
    api_key = api_key.strip().strip('"').strip("'")
    client = Anthropic(api_key=api_key)
    prompt = _baue_prompt(spieldaten, heim_info, gast_info, zitate_text, sperrfrist)

    # WICHTIG: max_tokens begrenzt, wie lang Claudes Antwort maximal werden
    # darf. Das bisherige Limit (3000) reichte fuer einen Nachbericht OHNE
    # Zitate meist aus, war aber zu knapp, sobald BEIDE Trainer-Zitate dazu-
    # kamen (laengerer O-Ton-Abschnitt + die Zitate fliessen zusaetzlich in
    # den Fliesstext ein) - die Antwort wurde dann mitten im Satz
    # abgeschnitten. Deshalb hier grosszuegiger bemessen.
    try:
        antwort = client.messages.create(
            model=MODELL,
            max_tokens=6000,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as fehler:  # lesbare Meldung statt anonymem Streamlit-Fehler
        status = getattr(fehler, "status_code", None)
        if status == 401:
            hinweis = (
                "API-Schluessel ungueltig oder abgelaufen (401). Bitte in den "
                "Streamlit-Secrets pruefen, ob der NEUE Schluessel vollstaendig "
                "und ohne Leerzeichen/Zeilenumbruch eingetragen ist, und die "
                "App danach neu starten (Reboot app)."
            )
        elif status == 403:
            hinweis = "Der Schluessel hat keine Berechtigung fuer dieses Modell oder diesen Workspace (403)."
        elif status == 404:
            hinweis = f"Modell '{MODELL}' wurde von der API nicht gefunden (404)."
        elif status == 429:
            hinweis = "Rate-Limit oder Ausgabenlimit des Schluessels erreicht (429)."
        else:
            hinweis = "Unerwarteter Fehler beim Aufruf der Claude-API."
        return f"Nachbericht konnte nicht erstellt werden: {hinweis}\n\nTechnische Details: {type(fehler).__name__}: {fehler}"

    text_bloecke = [block.text for block in antwort.content if block.type == "text"]
    if not text_bloecke:
        return "Claude hat keine Textantwort geliefert (nur Denk-Schritte). Bitte nochmal versuchen."

    # Sicherheitsnetz: Sollte die Antwort trotz des hoeheren Limits erneut
    # mitten im Text abgeschnitten worden sein (stop_reason "max_tokens"),
    # wird das als deutlicher Hinweis ans Ende angehaengt, statt den
    # abgeschnittenen Text kommentarlos auszugeben.
    abgeschnitten = getattr(antwort, "stop_reason", None) == "max_tokens"

    nachbericht_text = "\n".join(text_bloecke)
    if abgeschnitten:
        nachbericht_text += (
            "\n\n*(Hinweis: Die Antwort wurde vom Sprachmodell abgeschnitten - "
            "bitte 'Nachbericht generieren' ggf. erneut klicken oder die "
            "Zitate kürzen.)*"
        )
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
