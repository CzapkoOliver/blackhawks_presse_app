"""
Automatische Zwischensicherung des Spieltags-Protokolls.

PROBLEM: Streamlit haelt alle Eingaben (Strafzeiten, Tore, Notizen, das
geladene Spiel) nur im Arbeitsspeicher der jeweiligen Browser-Sitzung
("session_state"). Aktualisiert sich die Seite - egal ob durch F5, einen
Verbindungsabbruch (WLAN-Wechsel, Handy/Laptop im Ruhezustand), einen Klick
auf einen Menuepunkt mit Seitenwechsel oder einen Neustart der Verbindung -,
beginnt Streamlit eine NEUE Sitzung, und alles ist weg.

LOESUNG: Nach jedem Durchlauf wird der Stand in eine Datei auf dem Server
geschrieben. Beginnt eine neue, noch leere Sitzung, wird er daraus
wiederhergestellt. Die Sicherung ueberlebt damit Seitenaktualisierungen und
Verbindungsabbrueche. Sie ueberlebt NICHT einen Neustart/Neu-Deploy des
Servers (auf Streamlit Cloud: "Reboot app", ein neuer GitHub-Upload oder der
Ruhezustand der App nach Inaktivitaet) - waehrend eines Spiels also nichts
neu hochladen und die App nicht neu starten.

Alle Funktionen sind bewusst fehlertolerant: eine kaputte oder nicht
schreibbare Sicherung darf die App nie am Laufen hindern.
"""
from __future__ import annotations

import hashlib
import os
import pickle
import tempfile
import time
from pathlib import Path

# Nur diese Session-State-Schluessel werden gesichert (keine Widget-Zustaende
# wie halb ausgefuellte Formulare - die wuerden beim Wiederherstellen
# kollidieren).
GESICHERTE_SCHLUESSEL = (
    "daten",
    "gegner",
    "heim_info",
    "gast_info",
    "naechste_unser_team",
    "naechste_gegner",
    "logos",
    "kader",
    "kader_rohdaten",
    "strafzeiten_df",
    "tore_df",
    "sz_bloecke",
    "_bh_notizen",
    "fragen",
    "nachbericht",
    "roher_text_spielplan",
    "spielplan_anzahl",
    "roher_text_spielverlauf",
    "roher_text_spielbericht",
)

# Eine Sicherung gilt nur fuer den laufenden Spieltag - aeltere Staende
# werden ignoriert, damit nicht versehentlich ein Spiel von vor einer Woche
# wiederhergestellt wird.
MAX_ALTER_STUNDEN = 36
_VERSION = 1


def _sicherungs_datei() -> Path:
    """Pfad der Sicherungsdatei (per Umgebungsvariable ueberschreibbar, z.B. fuer Tests)."""
    ueberschrieben = os.getenv("BH_SICHERUNG_DATEI")
    if ueberschrieben:
        return Path(ueberschrieben)
    return Path(__file__).resolve().parent / ".sicherung" / "aktueller_spieltag.pkl"


def _schreibbare_datei() -> Path:
    """Bevorzugt den App-Ordner, weicht bei fehlenden Schreibrechten auf das Temp-Verzeichnis aus."""
    ziel = _sicherungs_datei()
    try:
        ziel.parent.mkdir(parents=True, exist_ok=True)
        pruefdatei = ziel.parent / ".schreibtest"
        pruefdatei.write_text("ok")
        pruefdatei.unlink()
        return ziel
    except Exception:
        return Path(tempfile.gettempdir()) / "bh_aktueller_spieltag.pkl"


def speichern(session_state) -> str | None:
    """
    Schreibt den aktuellen Stand, aber nur wenn sich seit der letzten
    Sicherung etwas geaendert hat. Gibt die Uhrzeit (HH:MM:SS) der letzten
    Sicherung zurueck oder None, falls (noch) nichts gesichert werden konnte.
    """
    try:
        if "daten" not in session_state:
            return session_state.get("_bh_letzte_sicherung")
        inhalt = {k: session_state[k] for k in GESICHERTE_SCHLUESSEL if k in session_state}
        rohdaten = pickle.dumps(inhalt, protocol=pickle.HIGHEST_PROTOCOL)
        pruefsumme = hashlib.sha256(rohdaten).hexdigest()
        if session_state.get("_bh_sicherung_hash") == pruefsumme:
            return session_state.get("_bh_letzte_sicherung")

        paket = {"version": _VERSION, "zeitpunkt": time.time(), "inhalt": inhalt}
        ziel = _schreibbare_datei()
        tmp = ziel.with_suffix(".tmp")
        with open(tmp, "wb") as f:
            pickle.dump(paket, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, ziel)  # atomar: nie eine halb geschriebene Sicherung

        uhrzeit = time.strftime("%H:%M:%S")
        session_state["_bh_sicherung_hash"] = pruefsumme
        session_state["_bh_letzte_sicherung"] = uhrzeit
        return uhrzeit
    except Exception:
        return session_state.get("_bh_letzte_sicherung")


def laden() -> dict | None:
    """Liest die Sicherung. None, wenn keine/zu alte/beschaedigte Sicherung vorliegt."""
    try:
        for kandidat in (_sicherungs_datei(), Path(tempfile.gettempdir()) / "bh_aktueller_spieltag.pkl"):
            if not kandidat.exists():
                continue
            with open(kandidat, "rb") as f:
                paket = pickle.load(f)
            if not isinstance(paket, dict) or paket.get("version") != _VERSION:
                continue
            alter_h = (time.time() - float(paket.get("zeitpunkt", 0))) / 3600
            if alter_h > MAX_ALTER_STUNDEN:
                continue
            inhalt = paket.get("inhalt")
            if isinstance(inhalt, dict) and "daten" in inhalt:
                paket["uhrzeit"] = time.strftime("%H:%M", time.localtime(paket["zeitpunkt"]))
                return paket
    except Exception:
        return None
    return None


def wiederherstellen(session_state) -> str | None:
    """
    Stellt eine vorhandene Sicherung in eine neue, leere Sitzung zurueck.
    Gibt die Uhrzeit der Sicherung zurueck (fuer die Hinweismeldung) oder
    None, wenn nichts wiederhergestellt wurde.
    """
    if "daten" in session_state:
        return None
    paket = laden()
    if not paket:
        return None
    for schluessel, wert in paket["inhalt"].items():
        if schluessel not in session_state:
            session_state[schluessel] = wert
    return paket["uhrzeit"]


def verwerfen() -> None:
    """Loescht die Sicherung (z.B. beim bewussten Start eines neuen Spiels)."""
    for kandidat in (_sicherungs_datei(), Path(tempfile.gettempdir()) / "bh_aktueller_spieltag.pkl"):
        try:
            kandidat.unlink()
        except Exception:
            pass
