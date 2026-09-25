"""
spieldaten.py
--------------
Holt die Spieldaten eines Oberliga-Sued-Spiels von DEB LIVE (deb-online.live)
und wertet sie in ein einfaches Dictionary aus.

Bestaetigt funktionierende URL-Form:
https://deb-online.live/spielbericht/?gameId=<GAME_ID>&divisionId=<DIVISION_ID>

Die Seite hat mehrere Reiter (Spielverlauf / Spielbericht / Shotmap). Wir
wechseln aktiv auf "Spielbericht" - dort stehen Besucherzahl, Schiedsrichter,
Trainer und die Team-Gesamtstatistik (u.a. Schuesse aufs Tor).
"""

import re
from collections import Counter

from playwright.sync_api import sync_playwright

# Beispiel-URL des Spiels SC Riessersee - EHF Passau Black Hawks (19.09.2026)
SPIELBERICHT_URL = (
    "https://deb-online.live/spielbericht/"
    "?gameId=08c9f551-d617-412e-a5db-bfb97c526728&divisionId=21614"
)


def hole_sichtbaren_text(url: str) -> tuple[str, str]:
    """
    Oeffnet die Spielbericht-Seite und liest den sichtbaren Text von ZWEI
    Reitern aus, im selben Browser-Durchlauf:
    - "Spielverlauf" (der Reiter, der beim Aufrufen der Seite standardmaessig
      aktiv ist) - hier stehen ALLE Spielereignisse chronologisch mit
      vollstaendigem Vor- und Nachnamen (Tore, Strafen, Torhueter-Wechsel).
      Wird bisher nur genutzt, um die Spielernamen zuverlaessiger/vollstaendiger
      zu erkennen (siehe nachbericht_generator.py) - alle anderen Felder
      werden unveraendert weiter aus "Spielbericht" gelesen, damit sich am
      bisherigen, bereits funktionierenden Verhalten nichts aendert.
    - "Spielbericht" - hier stehen Besucherzahl, Schiedsrichter, Trainer und
      die Team-Gesamtstatistik (u.a. Schuesse aufs Tor), wie bisher.

    Rueckgabe: (text_spielverlauf, text_spielbericht)
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, timeout=30000)
        page.wait_for_timeout(3000)

        # Cookie-Banner koennte den Klick blockieren - falls vorhanden, wegklicken.
        try:
            page.get_by_text("Alle akzeptieren", exact=False).first.click(timeout=3000)
            page.wait_for_timeout(1000)
        except Exception:
            pass

        # Der Reiter "Spielverlauf" ist beim Laden der Seite bereits aktiv -
        # deshalb hier einfach direkt den sichtbaren Text lesen, BEVOR auf
        # "Spielbericht" gewechselt wird. Schlaegt das Auslesen aus
        # irgendeinem Grund fehl, wird einfach ein leerer Text verwendet -
        # das darf die bisherige Auswertung (Spielbericht) nicht gefaehrden.
        try:
            text_spielverlauf = page.inner_text("body")
        except Exception:
            text_spielverlauf = ""

        reiter_geklickt = False
        versuche = [
            lambda: page.get_by_role("tab", name="Spielbericht", exact=True),
            lambda: page.get_by_role("button", name="Spielbericht", exact=True),
            lambda: page.get_by_text("Spielbericht", exact=True),
        ]
        for hole_element in versuche:
            try:
                element = hole_element().first
                element.click(timeout=3000)
                reiter_geklickt = True
                break
            except Exception:
                continue

        print(f"[Debug] Reiter 'Spielbericht' angeklickt: {reiter_geklickt}")
        page.wait_for_timeout(2500)

        text_spielbericht = page.inner_text("body")
        browser.close()
        return text_spielverlauf, text_spielbericht


# Grossbuchstaben-Bereich bewusst weiter gefasst als nur A-Z/ÄÖÜ (deckt z.B.
# auch "Á" in "KOVÁCS" oder "Č"/"Ř" in tschechischen Namen ab), da im
# Eishockey haeufig internationale Spielernamen vorkommen.
_SPIELER_NAME_MUSTER = re.compile(
    r"#\d+\s+([A-ZÀ-ÖØ-ÞČŘŠŽ][A-ZÀ-ÖØ-ÞČŘŠŽ'\- ]*[A-ZÀ-ÖØ-ÞČŘŠŽ])\s+"
    r"([A-ZÀ-ÖØ-ÞČŘŠŽ][A-Za-zÀ-ÖØ-öø-ÿčřšž'\-]*)"
)


def _baue_spieler_namen_verzeichnis(*texte: str) -> dict[str, str]:
    """
    Durchsucht die uebergebenen Seitentexte (typischerweise "Spielverlauf"
    UND "Spielbericht") nach JEDER Erwaehnung eines Spielers im Format
    "#Nummer NACHNAME Vorname" (z.B. "#22 HOBBS Grady") und baut daraus ein
    Nachschlage-Verzeichnis {Nachname: Vorname}.

    Der Reiter "Spielverlauf" listet dabei besonders viele Ereignisse
    (Tore, Strafen, Torhueter-Wechsel usw.), wodurch fast jeder Spieler
    mehrfach mit vollem Namen auftaucht - das macht die Namenserkennung
    robuster als sich nur auf die (kuerzere) Torschuetzen-Liste aus dem
    Spielbericht zu verlassen. Kommt ein Nachname mehrfach mit leicht
    unterschiedlicher Schreibweise vor, gewinnt die haeufigste Variante.
    """
    treffer_pro_nachname: dict[str, Counter] = {}
    for text in texte:
        if not text:
            continue
        for nachname_roh, vorname in _SPIELER_NAME_MUSTER.findall(text):
            nachname = nachname_roh.strip().title()
            treffer_pro_nachname.setdefault(nachname, Counter())[vorname.strip()] += 1

    return {
        nachname: zaehler.most_common(1)[0][0]
        for nachname, zaehler in treffer_pro_nachname.items()
    }


def parse_spielbericht(text: str, text_spielverlauf: str = "") -> dict:
    """
    Sucht im rohen Seitentext des "Spielbericht"-Reiters nach den benoetigten
    Werten und gibt sie als Dictionary zurueck. Werte, die nicht gefunden
    werden, bleiben None.

    text_spielverlauf ist optional: wird der Text des "Spielverlauf"-Reiters
    mituebergeben, verbessert das nur die Erkennung der Spielernamen (siehe
    "spieler_namen" unten und nachbericht_generator.py) - alle anderen
    Felder werden unveraendert wie bisher ausschliesslich aus "text"
    (Spielbericht) gelesen.
    """
    daten = {
        "heimteam": None,
        "gastteam": None,
        "endergebnis": None,
        "status": None,
        "ist_beendet": False,
        "schuesse_heim": None,
        "schuesse_gast": None,
        "zuschauer": None,
        "schiedsrichter": None,
        "linienrichter": None,
        "trainer_heim": None,
        "trainer_gast": None,
        "strafminuten_heim": None,
        "strafminuten_gast": None,
        "torfolge_pro_drittel": None,
        "tore_liste": None,
        "spieler_namen": None,
    }

    spieler_namen = _baue_spieler_namen_verzeichnis(text, text_spielverlauf)
    if spieler_namen:
        daten["spieler_namen"] = spieler_namen

    # Endergebnis + beide Teamnamen stehen direkt hintereinander, z.B.:
    # "4 : 2\nSC Riessersee\nSpiel beendet\nEHF Passau Black Hawks"
    #
    # Zuerst wird GENAU auf "Spiel beendet" geprueft (wie urspruenglich) -
    # das ist eindeutig und zuverlaessig. Ein voellig frei formuliertes
    # Muster (irgendein Text als "Status") hat sich in der Praxis an einer
    # falschen Stelle im Seitentext festgehakt und dadurch auch beendete
    # Spiele nicht mehr erkannt - deshalb NUR bekannte, typische Status-
    # Woerter fuer ein laufendes Spiel als Alternative zulassen.
    kopf_match_beendet = re.search(
        r"(\d+)\s*:\s*(\d+)\n([^\n]+)\nSpiel beendet\n([^\n]+)", text
    )
    if kopf_match_beendet:
        daten["endergebnis"] = f"{kopf_match_beendet.group(1)}:{kopf_match_beendet.group(2)}"
        daten["heimteam"] = kopf_match_beendet.group(3).strip()
        daten["gastteam"] = kopf_match_beendet.group(4).strip()
        daten["status"] = "Spiel beendet"
        daten["ist_beendet"] = True
    else:
        # DEB LIVE zeigt es manchmal so an: Das Spiel ist in Wirklichkeit
        # bereits vorbei (Endergebnis + komplette Statistik-Tabelle wie
        # Schuesse, PIM, Drittelergebnisse sind schon vollstaendig da),
        # aber die Statistiker haben den offiziellen Status noch nicht auf
        # "Spiel beendet" gesetzt - stattdessen steht dort nur das generische
        # Wort "Spiel" (ohne "beendet"). Ein wirklich noch laufendes Spiel
        # zeigt dagegen NIE nur "Spiel" allein an, sondern immer einen
        # laufzeit-/drittelbezogenen Hinweis (z.B. "1. Drittel" oder
        # "Spielzeit: 22:10", siehe die Faelle weiter unten) - deshalb kann
        # dieser Fall hier sicher als (praktisch) beendet behandelt werden,
        # statt die App bis zum Abbruch nach allen Versuchen warten zu lassen.
        kopf_match_generisch_beendet = re.search(
            r"(\d+)\s*:\s*(\d+)\n([^\n]+)\nSpiel\n([^\n]+)", text
        )
        if kopf_match_generisch_beendet:
            daten["endergebnis"] = f"{kopf_match_generisch_beendet.group(1)}:{kopf_match_generisch_beendet.group(2)}"
            daten["heimteam"] = kopf_match_generisch_beendet.group(3).strip()
            daten["gastteam"] = kopf_match_generisch_beendet.group(4).strip()
            daten["status"] = "Spiel beendet (Status auf DEB LIVE noch nicht aktualisiert)"
            daten["ist_beendet"] = True

        # Die beiden folgenden Erkennungsschritte (laufendes Spiel) werden nur
        # noch gebraucht, wenn oben WEDER "Spiel beendet" NOCH das generische
        # "Spiel" (= praktisch beendet) gefunden wurde - sonst wuerden sie die
        # bereits korrekt erkannten Daten wieder ueberschreiben/verwerfen.
        kopf_match_laeuft = None if kopf_match_generisch_beendet else re.search(
            r"(\d+)\s*:\s*(\d+)\n([^\n]+)\n"
            r"(\d\.\s*Drittel|Drittelpause|Pause|Verl(?:ä|ae)ngerung|"
            r"Nachspielzeit|Penaltyschie(?:ß|ss)en|Shootout|"
            r"Spielzeit\s*:\s*\d{1,2}:\d{2})"
            r"\n([^\n]+)",
            text,
            re.IGNORECASE,
        )
        if kopf_match_generisch_beendet:
            pass
        elif kopf_match_laeuft:
            daten["endergebnis"] = f"{kopf_match_laeuft.group(1)}:{kopf_match_laeuft.group(2)}"
            daten["heimteam"] = kopf_match_laeuft.group(3).strip()
            daten["status"] = kopf_match_laeuft.group(4).strip()
            daten["gastteam"] = kopf_match_laeuft.group(5).strip()
            daten["ist_beendet"] = False
        else:
            # Zweiter Versuch, bewusst SEHR tolerant: das obige Muster
            # verlangt eine exakte Zeilenfolge "Ergebnis / Heimteam /
            # EIN bekanntes Status-Wort / Gastteam". Waehrend eines
            # laufenden Spiels kann der genaue Wortlaut des Status
            # (z.B. "Spielzeit: 22:10") oder die Zeilenstruktur leicht
            # abweichen - ohne direkten Zugriff auf die Live-Seite laesst
            # sich das nicht vorab exakt vorhersagen. Deshalb hier NICHT
            # auf einen bestimmten Status-Text angewiesen sein, sondern
            # nur auf das eindeutig erkennbare Muster "Ergebnis, dann
            # Teamname, dann (evtl.) eine Statuszeile, dann Teamname"
            # in den Zeilen NACH dem Ergebnis.
            for ergebnis_match in re.finditer(r"^\s*(\d+)\s*:\s*(\d+)\s*$", text, re.MULTILINE):
                nachfolgende_zeilen = [
                    zeile.strip()
                    for zeile in text[ergebnis_match.end():].splitlines()[:6]
                    if zeile.strip()
                ]
                if len(nachfolgende_zeilen) < 2:
                    continue

                heimteam_kandidat = nachfolgende_zeilen[0]
                # Eine Zeile gilt als "Status" (statt als Teamname), wenn sie
                # eine Uhrzeit-/Minutenangabe (z.B. "22:10") enthaelt oder
                # eines der typischen Status-Woerter - so wird nicht auf
                # exakten Wortlaut gepocht, sondern auf das MUSTER.
                status_muster = re.compile(
                    r"\d{1,2}\s*:\s*\d{2}|Drittel|Pause|Verl(?:ä|ae)ngerung|"
                    r"Nachspielzeit|Penalty|Shootout|Halbzeit|beendet|laeuft|läuft",
                    re.IGNORECASE,
                )
                status_kandidat = None
                gastteam_kandidat = None
                for folge_zeile in nachfolgende_zeilen[1:]:
                    if status_muster.search(folge_zeile) and gastteam_kandidat is None:
                        status_kandidat = folge_zeile
                        continue
                    if status_kandidat is not None:
                        gastteam_kandidat = folge_zeile
                        break

                # Ein plausibler Teamname ist keine reine Zahl/Uhrzeit und
                # nicht leer - einfache Absicherung gegen Fehltreffer. Wichtig:
                # Es wird hier BEWUSST nur zugegriffen, wenn tatsaechlich eine
                # erkennbare Statuszeile gefunden wurde (status_kandidat).
                # Ohne das koennte sonst z.B. ein unbekannter Zwischentext
                # faelschlich als Gastteam-Name uebernommen werden - dann
                # lieber gar nichts erkennen (und die Diagnose-Anzeige in der
                # App greifen lassen) als falsche Team-/Trainerdaten anzeigen.
                def _wirkt_wie_teamname(wert: str) -> bool:
                    return bool(wert) and not re.fullmatch(r"[\d:\s]+", wert)

                if (
                    status_kandidat is not None
                    and _wirkt_wie_teamname(heimteam_kandidat)
                    and gastteam_kandidat
                    and _wirkt_wie_teamname(gastteam_kandidat)
                ):
                    daten["endergebnis"] = f"{ergebnis_match.group(1)}:{ergebnis_match.group(2)}"
                    daten["heimteam"] = heimteam_kandidat
                    daten["status"] = status_kandidat or "läuft (genauer Status unbekannt)"
                    daten["gastteam"] = gastteam_kandidat
                    daten["ist_beendet"] = False
                    break

    # Besucherzahl steht unter dem Label "Besucher" (nicht "Zuschauer"!)
    besucher_match = re.search(r"Besucher\s*\n\s*([\d.]+)", text)
    if besucher_match:
        daten["zuschauer"] = besucher_match.group(1).replace(".", "")

    # Schiedsrichter: "1. Schiedsrichter\nNAME\n2. Schiedsrichter\nNAME"
    schiedsrichter_treffer = re.findall(r"\d\.\s*Schiedsrichter\s*\n([^\n]+)", text)
    if schiedsrichter_treffer:
        daten["schiedsrichter"] = " / ".join(n.strip() for n in schiedsrichter_treffer)

    # Linienrichter, analog zu den Schiedsrichtern
    linienrichter_treffer = re.findall(r"\d\.\s*Linienrichter\s*\n([^\n]+)", text)
    if linienrichter_treffer:
        daten["linienrichter"] = " / ".join(n.strip() for n in linienrichter_treffer)

    # Cheftrainer: "Cheftrainer <TEAMKUERZEL>\n<NAME>" - zweimal (Heim + Gast),
    # in derselben Reihenfolge wie oben Heim-/Gastteam.
    trainer_treffer = re.findall(r"Cheftrainer\s+\S+\s*\n([^\n]+)", text)
    if len(trainer_treffer) >= 1:
        daten["trainer_heim"] = trainer_treffer[0].strip()
    if len(trainer_treffer) >= 2:
        daten["trainer_gast"] = trainer_treffer[1].strip()

    # Schuesse aufs Tor stehen eindeutig in der Team-Statistik-Tabelle
    schuesse_match = re.search(r"Sch(?:ü|u)sse auf das Tor\s+(\d+)\s+(\d+)", text)
    if schuesse_match:
        daten["schuesse_heim"] = int(schuesse_match.group(1))
        daten["schuesse_gast"] = int(schuesse_match.group(2))

    # Strafminuten (PIM = Penalty In Minutes) stehen direkt ueber den Schuessen
    # in derselben Team-Statistik-Tabelle, z.B. "PIM  13  13"
    pim_match = re.search(r"\bPIM\s+(\d+)\s+(\d+)", text)
    if pim_match:
        daten["strafminuten_heim"] = int(pim_match.group(1))
        daten["strafminuten_gast"] = int(pim_match.group(2))

    # Torfolge pro Drittel: aus der "TORE"-Tabelle den jeweiligen Spielstand
    # nach jedem Tor auslesen und daraus berechnen, wie viele Tore jedes Team
    # in welchem Drittel erzielt hat (z.B. um "3 Gegentore im 1. Drittel" zu
    # erkennen, auch wenn das Endergebnis am Ende knapp aussieht).
    tore_abschnitt_match = re.search(r"\bTORE\b\n(.*?)\n\s*STRAFEN\b", text, re.DOTALL)
    if tore_abschnitt_match:
        tore_abschnitt_text = tore_abschnitt_match.group(1)
        tore_zeilen = re.findall(
            r"^(\d)\s+\d{1,2}:\d{2}\s+(\d+):(\d+)\b",
            tore_abschnitt_text,
            re.MULTILINE,
        )

        # Fuer den spaeteren Nachbericht (siehe nachbericht_generator.py) wird
        # zusaetzlich zur reinen Drittel-Zusammenfassung auch die einzelne
        # Torschuetzen-Zeile aufbewahrt (z.B. Name/Vorlage), damit der
        # Nachbericht eine echte Torchronologie enthalten kann. Der Torschuetzen-
        # Text kann je nach Seitenaufbau auf derselben Zeile ODER den
        # Folgezeilen stehen - deshalb wird hier alles zwischen dem Beginn
        # einer Tor-Zeile und dem Beginn der naechsten Tor-Zeile eingesammelt,
        # statt nur die eine Zeile selbst auszuwerten.
        tore_zeilen_positionen = list(
            re.finditer(r"^(\d)\s+(\d{1,2}:\d{2})\s+(\d+):(\d+)\b", tore_abschnitt_text, re.MULTILINE)
        )
        tore_liste = []
        for i, treffer in enumerate(tore_zeilen_positionen):
            start_naechste = (
                tore_zeilen_positionen[i + 1].start()
                if i + 1 < len(tore_zeilen_positionen)
                else len(tore_abschnitt_text)
            )
            rest_text = tore_abschnitt_text[treffer.end():start_naechste].strip()
            rest_text = " ".join(zeile.strip() for zeile in rest_text.splitlines() if zeile.strip())

            # Zusaetzlich zum rohen Text wird der Torschuetzen-Name sauber
            # herausgeloest (z.B. aus "(EQ) #22 HOBBS Grady (#79 MÖSSINGER / ...)"
            # wird "Grady Hobbs"). Grund: Wird nur der rohe Text an Claude
            # uebergeben, kommt es beim freien Formulieren des Nachberichts
            # gelegentlich zu vertauschten/verwechselten Vornamen (z.B. "Grady"
            # wird zu "Grant"). Ein bereits sauber vorbereiteter Name senkt
            # dieses Risiko deutlich, siehe zusaetzlich die Namens-Korrektur
            # in nachbericht_generator.py als weiteres Sicherheitsnetz.
            torschuetze = None
            schuetze_match = _SPIELER_NAME_MUSTER.search(rest_text)
            if schuetze_match:
                nachname = schuetze_match.group(1).strip().title()
                # Bevorzugt den Vornamen aus dem umfassenderen Namens-
                # verzeichnis (mehrere Erwaehnungen ueber Spielverlauf +
                # Spielbericht) - nur falls dort nichts hinterlegt ist, wird
                # auf den direkt hier gefundenen Vornamen zurueckgegriffen.
                vorname = spieler_namen.get(nachname) or schuetze_match.group(2).strip()
                torschuetze = f"{vorname} {nachname}"

            tore_liste.append(
                {
                    "drittel": int(treffer.group(1)),
                    "zeit": treffer.group(2),
                    "stand": f"{treffer.group(3)}:{treffer.group(4)}",
                    "info": rest_text,
                    "torschuetze": torschuetze,
                }
            )
        if tore_liste:
            daten["tore_liste"] = tore_liste
        # Wichtig: Ein Drittel, in dem KEIN Tor gefallen ist (0:0), taucht in
        # der TORE-Tabelle gar nicht auf - es gibt schlicht keine Zeile dafuer.
        # Deshalb reicht es nicht, nur die Drittel mit tatsaechlichen Treffern
        # in "drittel_tore" einzutragen: sonst fehlt ein torloses Drittel in
        # der Anzeige komplett, statt korrekt als 0:0 zu erscheinen.
        drittel_tore: dict[int, list[int]] = {}
        letzter_heim, letzter_gast = 0, 0
        for drittel_text, heim_stand_text, gast_stand_text in tore_zeilen:
            drittel = int(drittel_text)
            heim_stand, gast_stand = int(heim_stand_text), int(gast_stand_text)
            heim_tore, gast_tore = drittel_tore.setdefault(drittel, [0, 0])
            drittel_tore[drittel][0] = heim_tore + (heim_stand - letzter_heim)
            drittel_tore[drittel][1] = gast_tore + (gast_stand - letzter_gast)
            letzter_heim, letzter_gast = heim_stand, gast_stand

        # Regulaer werden immer 3 Drittel gespielt. Kam es zur Verlaengerung,
        # gibt es mindestens ein Tor mit Drittel-Nummer 4 (oder hoeher) - dann
        # wird bis dorthin aufgefuellt. Jedes torlose Drittel dazwischen wird
        # explizit mit 0:0 ergaenzt, statt einfach zu fehlen.
        hoechstes_drittel = max([3] + [int(d) for d, _, _ in tore_zeilen])
        for drittel in range(1, hoechstes_drittel + 1):
            drittel_tore.setdefault(drittel, [0, 0])

        daten["torfolge_pro_drittel"] = drittel_tore

    return daten


if __name__ == "__main__":
    roher_text_spielverlauf, roher_text = hole_sichtbaren_text(SPIELBERICHT_URL)
    ergebnis = parse_spielbericht(roher_text, roher_text_spielverlauf)

    print("----- AUSGEWERTETE SPIELDATEN -----")
    for feld, wert in ergebnis.items():
        status = wert if wert is not None else "NICHT GEFUNDEN"
        print(f"{feld}: {status}")

    fehlend = [k for k, v in ergebnis.items() if v is None]
    if fehlend:
        print("\nFolgende Felder wurden nicht gefunden:", ", ".join(fehlend))
        print("Tipp: Schick den Rohtext (unten) an Claude, um die Muster anzupassen.")
        print("\n----- ROHER SEITENTEXT (zur Fehlersuche) -----")
        print(roher_text)
