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
from playwright.sync_api import sync_playwright

# Beispiel-URL des Spiels SC Riessersee - EHF Passau Black Hawks (19.09.2026)
SPIELBERICHT_URL = (
    "https://deb-online.live/spielbericht/"
    "?gameId=08c9f551-d617-412e-a5db-bfb97c526728&divisionId=21614"
)


def hole_sichtbaren_text(url: str) -> str:
    """
    Oeffnet die Spielbericht-Seite, wechselt aktiv auf den Reiter
    "Spielbericht" und gibt den kompletten sichtbaren Text zurueck.
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

        text = page.inner_text("body")
        browser.close()
        return text


def parse_spielbericht(text: str) -> dict:
    """
    Sucht im rohen Seitentext des "Spielbericht"-Reiters nach den benoetigten
    Werten und gibt sie als Dictionary zurueck. Werte, die nicht gefunden
    werden, bleiben None.
    """
    daten = {
        "heimteam": None,
        "gastteam": None,
        "endergebnis": None,
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
    }

    # Endergebnis + beide Teamnamen stehen direkt hintereinander, z.B.:
    # "4 : 2\nSC Riessersee\nSpiel beendet\nEHF Passau Black Hawks"
    kopf_match = re.search(
        r"(\d+)\s*:\s*(\d+)\n([^\n]+)\nSpiel beendet\n([^\n]+)", text
    )
    if kopf_match:
        daten["endergebnis"] = f"{kopf_match.group(1)}:{kopf_match.group(2)}"
        daten["heimteam"] = kopf_match.group(3).strip()
        daten["gastteam"] = kopf_match.group(4).strip()

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
        tore_zeilen = re.findall(
            r"^(\d)\s+\d{1,2}:\d{2}\s+(\d+):(\d+)\b",
            tore_abschnitt_match.group(1),
            re.MULTILINE,
        )
        if tore_zeilen:
            drittel_tore: dict[int, list[int]] = {}
            letzter_heim, letzter_gast = 0, 0
            for drittel_text, heim_stand_text, gast_stand_text in tore_zeilen:
                drittel = int(drittel_text)
                heim_stand, gast_stand = int(heim_stand_text), int(gast_stand_text)
                heim_tore, gast_tore = drittel_tore.setdefault(drittel, [0, 0])
                drittel_tore[drittel][0] = heim_tore + (heim_stand - letzter_heim)
                drittel_tore[drittel][1] = gast_tore + (gast_stand - letzter_gast)
                letzter_heim, letzter_gast = heim_stand, gast_stand
            daten["torfolge_pro_drittel"] = drittel_tore

    return daten


if __name__ == "__main__":
    roher_text = hole_sichtbaren_text(SPIELBERICHT_URL)
    ergebnis = parse_spielbericht(roher_text)

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
