"""
spielplan.py
-------------
Liest die Oberliga-Sued-Spielplanseite aus und findet die naechsten
anstehenden Spiele einer bestimmten Mannschaft.

Trick beim Auswerten: In der Tabelle sind Heimteam und Gastteam durch
unterschiedlich viele Leerzeichen getrennt - bei manchen Zeilen reicht der
Abstand zwischen Gastteam und Spielort aber nicht aus, um sie sauber zu
trennen (z.B. "Hockey Club Tigers 1985 Passau - Eis-Arena"). Deshalb gehen
wir zweistufig vor:
  1. Alle Heimteam-Namen einsammeln (die sind immer sauber durch ":" getrennt)
     -> das ergibt automatisch die komplette Liste aller Liga-Teams.
  2. Für den Rest jeder Zeile (Gastteam + Spielort zusammen) das laengste
     bekannte Team aus Schritt 1 als Praefix suchen - der Rest dahinter ist
     der Spielort.
"""

import re
from datetime import datetime
from playwright.sync_api import sync_playwright

SPIELPLAN_URL = "https://deb-online.live/liga/herren/oberliga-sued/?divisionId=21614"

ZEILEN_MUSTER = re.compile(
    r"^(\d{2}\.\d{2}\.\d{4})\s+(\d{1,2}:\d{2})\s+(.+?)\s{2,}:\s*(.+)$",
    re.MULTILINE,
)


def hole_sichtbaren_text(url: str) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        # Grosszuegiger warten als zuvor - auf einer langsameren Verbindung
        # oder bei einer langsam ladenden Seite wurde sonst der Klick auf
        # "Spielplan"/"Ergebnisse"/"Spiele" verpasst, weil der Button zu
        # diesem Zeitpunkt noch gar nicht da war - Ergebnis: 0 erkannte Spiele,
        # obwohl die Seite an sich erreichbar war.
        page.goto(url, timeout=45000)
        page.wait_for_load_state("networkidle", timeout=15000)
        page.wait_for_timeout(4000)
        try:
            page.get_by_text("Alle akzeptieren", exact=False).first.click(timeout=3000)
            page.wait_for_timeout(1000)
        except Exception:
            pass
        geklickt = False
        for name in ["Spielplan", "Ergebnisse", "Spiele", "Tabelle"]:
            try:
                page.get_by_text(name, exact=True).first.click(timeout=3000)
                page.wait_for_timeout(2000)
                geklickt = True
                break
            except Exception:
                continue
        # Falls kein Reiter-Button gefunden/geklickt werden konnte, noch
        # etwas laenger warten, bevor der Text ausgelesen wird - manche
        # Versionen der Seite zeigen den Spielplan ggf. direkt an.
        if not geklickt:
            page.wait_for_timeout(2000)
        text = page.inner_text("body")
        browser.close()
        return text


def parse_spielplan(text: str) -> list[dict]:
    """Gibt eine Liste aller gefundenen Spiele zurueck, sortiert nach Datum."""

    # Schritt 1: Rohzeilen einsammeln + bekannte Heimteam-Namen sammeln
    rohzeilen = []
    bekannte_teams = set()
    for zeile in ZEILEN_MUSTER.finditer(text):
        datum_text, zeit_text, heim, rest = zeile.groups()
        heim = heim.strip()
        bekannte_teams.add(heim)
        rohzeilen.append((datum_text, zeit_text, heim, rest.strip()))

    # Laengste Teamnamen zuerst pruefen, damit z.B. "Hockey Club Tigers 1985"
    # nicht faelschlich als Teil eines laengeren Namens abgeschnitten wird.
    teams_nach_laenge = sorted(bekannte_teams, key=len, reverse=True)

    spiele = []
    for datum_text, zeit_text, heim, rest in rohzeilen:
        gast = None
        ort = ""
        for team in teams_nach_laenge:
            if rest.startswith(team):
                gast = team
                ort = rest[len(team):].strip()
                break
        if gast is None:
            # Konnte nicht sicher zugeordnet werden - Zeile ueberspringen,
            # lieber ein fehlendes Spiel als ein falsches.
            continue
        try:
            datum = datetime.strptime(f"{datum_text} {zeit_text}", "%d.%m.%Y %H:%M")
        except ValueError:
            continue
        spiele.append({"datum": datum, "heim": heim, "gast": gast, "ort": ort})

    spiele.sort(key=lambda s: s["datum"])
    return spiele


def _namen_passen_zusammen(a: str, b: str) -> bool:
    """
    Vergleicht zwei Teamnamen tolerant: nicht nur exakt gleich, sondern auch
    wenn einer im anderen enthalten ist (z.B. "EHF Passau Black Hawks" auf dem
    Spielbericht vs. nur "Passau Black Hawks" auf der Spielplan-Seite). Ohne
    das wurden "Naechste Spiele" bei kleinsten Schreibweise-Unterschieden
    stillschweigend leer zurueckgegeben, obwohl der Spielplan an sich korrekt
    ausgelesen wurde.
    """
    a = a.lower().strip()
    b = b.lower().strip()
    if not a or not b:
        return False
    return a == b or a in b or b in a


def naechste_spiele(spiele: list[dict], team: str, nach_datum: datetime, anzahl: int = 2) -> list[dict]:
    """
    Filtert alle Spiele einer Mannschaft (egal ob Heim oder Gast), die NACH
    dem angegebenen Datum stattfinden, und gibt die ersten `anzahl` davon zurueck.
    """
    treffer = [
        s for s in spiele
        if s["datum"] > nach_datum
        and (_namen_passen_zusammen(team, s["heim"]) or _namen_passen_zusammen(team, s["gast"]))
    ]
    return treffer[:anzahl]


if __name__ == "__main__":
    text = hole_sichtbaren_text(SPIELPLAN_URL)
    alle_spiele = parse_spielplan(text)
    print(f"[Debug] {len(alle_spiele)} Spiele im Spielplan erkannt")

    # Beispiel: Datum des zuletzt gespielten Spiels (Riessersee - Passau, 19.09.2026)
    letztes_spiel_datum = datetime(2026, 9, 19)

    print("\nNaechste Spiele: EHF Passau Black Hawks")
    for s in naechste_spiele(alle_spiele, "EHF Passau Black Hawks", letztes_spiel_datum):
        print(f"  {s['datum'].strftime('%d.%m.%Y %H:%M')} - {s['heim']} vs {s['gast']} ({s['ort']})")

    print("\nNaechste Spiele: SC Riessersee (Beispiel-Gegner)")
    for s in naechste_spiele(alle_spiele, "SC Riessersee", letztes_spiel_datum):
        print(f"  {s['datum'].strftime('%d.%m.%Y %H:%M')} - {s['heim']} vs {s['gast']} ({s['ort']})")
