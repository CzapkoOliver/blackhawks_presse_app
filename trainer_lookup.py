"""
trainer_lookup.py
------------------
Liest trainer.csv aus und findet zu einem auf DEB LIVE gefundenen Trainernamen
(z.B. "REJA DANIEL", Vor-/Nachname oft vertauscht und in Grossbuchstaben) die
passende Zeile - unabhaengig von der Reihenfolge von Vor- und Nachname.
"""

import csv

TRAINER_DATEI = "trainer.csv"


def normalisieren(name: str) -> frozenset:
    """
    Macht aus einem Namen eine Menge von Woertern in Kleinbuchstaben, damit
    "REJA DANIEL" und "Daniel Reja" als gleich erkannt werden.
    """
    return frozenset(wort.lower() for wort in name.split())


def lade_trainer_tabelle(pfad: str = TRAINER_DATEI) -> list[dict]:
    with open(pfad, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def finde_trainer(name: str, tabelle: list[dict]) -> dict | None:
    """
    Sucht den Trainernamen in der Tabelle. Gibt das gefundene Dictionary
    zurueck (team, trainer_name, nationalitaet, sprache) oder None, wenn er
    nicht gefunden wurde bzw. die Zeile noch nicht ausgefuellt ist.
    """
    gesucht = normalisieren(name)
    for zeile in tabelle:
        eintrag_name = zeile.get("trainer_name", "").strip()
        if not eintrag_name:
            continue
        if normalisieren(eintrag_name) == gesucht:
            if zeile.get("nationalitaet") and zeile.get("sprache"):
                return zeile
    return None


def hole_nationalitaet_und_sprache(name: str) -> dict:
    """
    Komfort-Funktion fuer die App: gibt immer ein Dictionary mit
    nationalitaet/sprache zurueck - auch wenn nichts gefunden wurde
    (dann "unbekannt", damit die App weiss, dass Nachfragen noetig ist).
    """
    tabelle = lade_trainer_tabelle()
    treffer = finde_trainer(name, tabelle)
    if treffer:
        return {
            "nationalitaet": treffer["nationalitaet"],
            "sprache": treffer["sprache"],
        }
    return {"nationalitaet": "unbekannt", "sprache": "unbekannt"}


if __name__ == "__main__":
    # Kleiner Test mit den Trainern aus dem echten Spiel (Grossbuchstaben, wie
    # sie von der DEB-LIVE-Seite kommen).
    for testname in ["REJA DANIEL", "CARLSSON LEIF", "MUSTERMANN MAX"]:
        ergebnis = hole_nationalitaet_und_sprache(testname)
        print(f"{testname}: {ergebnis}")
