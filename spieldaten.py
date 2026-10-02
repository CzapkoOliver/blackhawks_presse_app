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


def hole_sichtbaren_text(url: str) -> tuple[str, str, dict]:
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

    Zusaetzlich werden die Bild-URLs der beiden Vereinswappen eingesammelt
    (siehe "logos" unten) - fuer die Darstellung in der App muss dafuer kein
    Bild selbst heruntergeladen werden, der Browser des Betrachters laedt es
    direkt von der Original-Adresse.

    Rueckgabe: (text_spielverlauf, text_spielbericht, logos, kader_rohdaten)
    "logos" ist ein Dict {"heim": URL_oder_None, "gast": URL_oder_None}.
    "kader_rohdaten" ist ein Dict {team_kuerzel: gesammelter_seitentext} -
    ein Eintrag je gefundenem Kuerzel-Button (z.B. "EHF"/"HCT"), siehe
    Kommentar oben. Die Zuordnung zu "heim"/"gast" erfolgt erst in
    kader_pro_team(), da hier die vollen Teamnamen noch nicht bekannt sind.
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

        # Zusaetzlich: die Kaderliste ("FELDSPIELER"/"GOALIES"-Tabelle) BEIDER
        # Mannschaften einsammeln - dort steht IMMER der volle, ausgeschriebene
        # Vorname (z.B. "HOBBS Grady"), unabhaengig davon, ob die Torschuetzen-
        # Liste selbst nur abgekuerzte Vornamen zeigt (z.B. "MACKINNON J.").
        # Bestaetigt durch echte DevTools-Screenshots des Nutzers: JEDER
        # Daten-Abschnitt (Feldspieler, Goalies, Goalie-Wechsel, Strafen) hat
        # einen EIGENEN, unabhaengigen ".-hd-button-group" mit je einem
        # eigenen "EHF"/"HCT"-Button-Paar - es gibt also MEHRERE gleichnamige
        # Buttons auf der Seite, keinen einzigen seitenweiten Filter.
        #
        # Fruehere Version (Fehler, fuehrte zur gemeldeten Vermischung von
        # Rueckennummern/Namen zwischen den Mannschaften): alle gleichnamigen
        # Buttons über die GANZE Seite hinweg nacheinander anklicken und
        # danach jeweils den GESAMTEN <body>-Text einsammeln. Da die Toggles
        # unabhaengig voneinander sind, war der <body>-Text nach einem Klick
        # oft eine Mischung aus den (bereits wieder veraenderten) Zustaenden
        # mehrerer Abschnitte.
        #
        # Fix: Klick UND Text-Erfassung werden strikt je Abschnitt (Container)
        # skaliert - es wird nur innerhalb des jeweiligen Containers geklickt
        # und auch nur dessen eigener Text (nicht der ganzen Seite) direkt
        # danach eingesammelt. Treffer desselben Kuerzels aus mehreren
        # Abschnitten (z.B. einmal Feldspieler, einmal Goalies) werden unter
        # demselben Schluessel zusammengefuegt. Die Zuordnung Kuerzel ->
        # "heim"/"gast" erfolgt weiterhin separat in kader_pro_team(), da
        # dort erst die vollen Teamnamen bekannt sind.
        kader_container_selektoren = [
            ".-hd-los-game-full-report-field-players",
            ".-hd-los-game-full-report-goal-keepers",
            ".-hd-los-game-full-report-goal-keeper-changes",
            ".-hd-los-game-full-report-penalties",
        ]
        kader_rohdaten: dict[str, str] = {}
        for selektor in kader_container_selektoren:
            try:
                container = page.locator(selektor).first
                if container.count() == 0:
                    continue
                buttons = container.locator(".-hd-button-group button")
                anzahl_buttons = min(buttons.count(), 10)
            except Exception:
                continue
            for i in range(anzahl_buttons):
                try:
                    knopf = buttons.nth(i)
                    knopf_text = knopf.inner_text(timeout=800).strip()
                except Exception:
                    continue
                if not re.fullmatch(r"[A-ZÄÖÜ]{2,5}", knopf_text):
                    continue
                try:
                    knopf.click(timeout=1500)
                    page.wait_for_timeout(500)
                    text_nach_klick = container.inner_text(timeout=2000)
                except Exception:
                    continue
                kader_rohdaten[knopf_text] = kader_rohdaten.get(knopf_text, "") + "\n" + text_nach_klick

        # Fallback: falls keiner der oben erwarteten Container-Selektoren auf
        # der Seite gefunden wurde (z.B. weil DEB LIVE die Klassennamen
        # irgendwann aendert), wird - wie in der Vorversion - versucht, ALLE
        # gleichnamigen Buttons auf der gesamten Seite anzuklicken. Das birgt
        # zwar wieder das Vermischungsrisiko, ist aber besser als gar keine
        # Kaderliste zu erhalten; die Diagnose-Anzeige in der App macht ein
        # solches Vermischen sichtbar (identische Rohtexte je Kuerzel).
        if not kader_rohdaten:
            try:
                alle_buttons = page.get_by_role("button")
                anzahl_buttons = min(alle_buttons.count(), 40)
                for i in range(anzahl_buttons):
                    try:
                        knopf = alle_buttons.nth(i)
                        knopf_text = knopf.inner_text(timeout=800).strip()
                    except Exception:
                        continue
                    if not re.fullmatch(r"[A-ZÄÖÜ]{2,5}", knopf_text):
                        continue
                    try:
                        knopf.click(timeout=1500)
                        page.wait_for_timeout(700)
                        text_nach_klick = page.inner_text("body")
                    except Exception:
                        continue
                    kader_rohdaten[knopf_text] = kader_rohdaten.get(knopf_text, "") + "\n" + text_nach_klick
            except Exception:
                pass

        # Fuer die Namenserkennung (siehe _baue_spieler_namen_aus_kaderliste
        # oben, Team-unabhaengig) wird weiterhin einfach alles zusammen
        # angehaengt - das Pooling dort ist bewusst teamunabhaengig und
        # schadet nicht, siehe Docstring dort.
        if kader_rohdaten:
            text_spielverlauf = text_spielverlauf + "\n" + "\n".join(kader_rohdaten.values())

        # Vereinswappen beider Mannschaften: die beiden auffaellig GROSSEN
        # Bilder im Spielbereich (deutlich groesser als Icons/Flaggen und
        # unterhalb der oberen Navigationsleiste, z.B. dem kleinen DEB-
        # Verbandslogo) sind die Wappen - von links nach rechts erst Heim,
        # dann Gast. Es wird nur die Bild-ADRESSE mitgenommen, nicht das Bild
        # selbst heruntergeladen (siehe Docstring oben).
        logos = {"heim": None, "gast": None}
        try:
            from urllib.parse import urljoin

            bilder = page.locator("img")
            anzahl_bilder = min(bilder.count(), 30)
            kandidaten = []
            for i in range(anzahl_bilder):
                bild = bilder.nth(i)
                try:
                    box = bild.bounding_box(timeout=500)
                    src = bild.get_attribute("src", timeout=500)
                except Exception:
                    continue
                if not box or not src:
                    continue
                if box["width"] >= 50 and box["height"] >= 50 and box["y"] > 100:
                    absolute_url = src if src.startswith("data:") else urljoin(page.url, src)
                    kandidaten.append((box["y"], box["x"], absolute_url))
            kandidaten.sort(key=lambda k: (k[0], k[1]))
            if len(kandidaten) >= 2:
                logos["heim"] = kandidaten[0][2]
                logos["gast"] = kandidaten[1][2]
            elif len(kandidaten) == 1:
                logos["heim"] = kandidaten[0][2]
        except Exception:
            pass

        browser.close()
        return text_spielverlauf, text_spielbericht, logos, kader_rohdaten


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


# Fuer die Kaderliste ("FELDSPIELER"/"GOALIES"-Tabelle, Spalten "#", "Spieler",
# "Pos", "Land", ...): ein komplett grossgeschriebenes Wort (Nachname-Teil).
_GROSSBUCHSTABEN_TOKEN = re.compile(r"^[A-ZÀ-ÖØ-ÞČŘŠŽ´`'\-]{2,}$")
# Ein "normal" grossgeschriebenes Wort (erster Buchstabe gross, Rest nicht
# komplett gross) - das ist der Vorname, z.B. "Tom" oder "Jan-Luka".
_TITEL_TOKEN = re.compile(r"^[A-ZÀ-ÖØ-ÞČŘŠŽ][A-Za-zÀ-ÖØ-öø-ÿčřšž'\-]*$")


def _baue_spieler_namen_aus_kaderliste(*texte: str) -> dict[str, str]:
    """
    Zweite, von "#Nummer"-Erwaehnungen UNABHAENGIGE Quelle fuer volle
    Spielernamen: die Kaderliste/Boxscore-Tabelle, wie sie je Team auf der
    Spielbericht-Seite zu sehen ist (Spalten "#", "Spieler", "Pos", "Land",
    ...), z.B. eine Tabellenzeile wie "6  HORSCHEL Tom  LD  GER  1  0  1 ...".
    Dort steht IMMER der volle, ausgeschriebene Vorname - unabhaengig davon,
    ob die Torschuetzen-/Strafenliste selbst nur abgekuerzte Vornamen zeigt
    (z.B. "MACKINNON J." statt "MACKINNON John").

    Technik: der Text wird in einzelne Woerter zerlegt (unabhaengig davon, ob
    die Tabellenzellen beim Auslesen durch Tabs, Leerzeichen oder Zeilen-
    umbrueche getrennt sind), und es wird nach der charakteristischen
    Reihenfolge "Rueckennummer (1-3 Ziffern), ein oder mehrere KOMPLETT
    GROSSGESCHRIEBENE Woerter (Nachname), dann genau EIN normal
    grossgeschriebenes Wort (Vorname)" gesucht. Dieses Muster ist spezifisch
    genug, um nicht versehentlich an anderer Stelle der Seite (z.B. in einer
    Tor- oder Strafenliste mit anderen Zahlen) zuzuschlagen.
    """
    treffer_pro_nachname: dict[str, Counter] = {}
    for text in texte:
        if not text:
            continue
        tokens = text.split()
        i = 0
        while i < len(tokens):
            if tokens[i].isdigit() and 1 <= len(tokens[i]) <= 3:
                j = i + 1
                nachname_tokens = []
                while j < len(tokens) and _GROSSBUCHSTABEN_TOKEN.match(tokens[j]):
                    nachname_tokens.append(tokens[j])
                    j += 1
                if (
                    nachname_tokens
                    and j < len(tokens)
                    and _TITEL_TOKEN.match(tokens[j])
                    and not _GROSSBUCHSTABEN_TOKEN.match(tokens[j])
                ):
                    nachname = " ".join(nachname_tokens).title()
                    vorname = tokens[j]
                    treffer_pro_nachname.setdefault(nachname, Counter())[vorname] += 1
                    i = j + 1
                    continue
            i += 1

    return {
        nachname: zaehler.most_common(1)[0][0]
        for nachname, zaehler in treffer_pro_nachname.items()
    }


def _kader_aus_text(text: str) -> dict[str, str]:
    """
    Wie _baue_spieler_namen_aus_kaderliste(), aber fuer GENAU EINEN
    Textabschnitt (idealerweise bereits auf eine einzelne Mannschaft
    eingegrenzt, siehe kader_pro_team()) und mit der Rueckennummer als
    Schluessel statt dem Nachnamen - das wird fuer die Strafzeiten-Erfassung
    gebraucht (Dropdown "Spielernummer" -> Name).
    """
    kader: dict[str, str] = {}
    tokens = text.split()
    i = 0
    while i < len(tokens):
        if tokens[i].isdigit() and 1 <= len(tokens[i]) <= 3:
            nummer = tokens[i]
            j = i + 1
            nachname_tokens = []
            while j < len(tokens) and _GROSSBUCHSTABEN_TOKEN.match(tokens[j]):
                nachname_tokens.append(tokens[j])
                j += 1
            if (
                nachname_tokens
                and j < len(tokens)
                and _TITEL_TOKEN.match(tokens[j])
                and not _GROSSBUCHSTABEN_TOKEN.match(tokens[j])
            ):
                nachname = " ".join(nachname_tokens).title()
                vorname = tokens[j]
                kader[nummer] = f"{vorname} {nachname}"
                i = j + 1
                continue
        i += 1
    return kader


def _erste_fundstelle(text: str, teamname: str) -> int | None:
    """
    Sucht die erste Fundstelle eines Teamnamens in einem Text, toleranter als
    ein exakter Treffer: zuerst der volle Name, dann (falls nicht gefunden)
    nur die letzten zwei Woerter, dann nur das letzte Wort - z.B. findet das
    auch "Black Hawks" oder "Hawks", wenn "EHF Passau Black Hawks" in der
    Kaderliste selbst leicht anders/abgekuerzt geschrieben steht. Gibt None
    zurueck, wenn gar keine der Varianten gefunden wird.
    """
    if not text or not teamname:
        return None
    text_l = text.lower()
    worte = teamname.split()
    kandidaten = [teamname.strip()]
    if len(worte) >= 2:
        kandidaten.append(" ".join(worte[-2:]))
    if worte:
        kandidaten.append(worte[-1])
    for kandidat in kandidaten:
        pos = text_l.find(kandidat.lower())
        if pos != -1:
            return pos
    return None


def _team_kuerzel_passt(kuerzel: str, teamname: str) -> bool:
    """
    Prueft tolerant, ob ein Team-Kuerzel-Button (z.B. "EHF", "HCT", "ECP") zu
    einem vollen Teamnamen gehoert. Drei Faelle werden abgedeckt:
    (1) das Kuerzel kommt woertlich im Teamnamen vor
        ("EHF" in "EHF Passau Black Hawks"),
    (2) das Kuerzel sind die Anfangsbuchstaben JEDES einzelnen Wortteils
        ("HCT" aus "Hockey Club Tigers 1985"),
    (3) das Kuerzel besteht aus dem ERSTEN Wort KOMPLETT (haeufig selbst
        schon eine Vereins-Abkuerzung wie "EC", "ESC", "ERC", "EV", "TSV",
        ...) gefolgt von je einem Anfangsbuchstaben der weiteren Wortteile
        ("ECP" aus "EC Peiting" = "EC" + "P") - bestaetigt durch einen
        echten Fall, bei dem Variante (2) allein ("EP") nicht zum von DEB
        LIVE verwendeten Kuerzel "ECP" passte und das Team dadurch gar
        keiner Rolle (heim/gast) zugeordnet wurde.
    """
    if not kuerzel or not teamname:
        return False
    kuerzel_l = kuerzel.strip().lower()
    teamname_l = teamname.lower()
    if kuerzel_l in teamname_l:
        return True

    worte = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]+", teamname)
    if not worte:
        return False

    kandidaten = {"".join(wort[0] for wort in worte).lower()}
    if len(worte) >= 2:
        kandidaten.add((worte[0] + "".join(wort[0] for wort in worte[1:])).lower())

    return any(
        kuerzel_l == kandidat or kandidat.startswith(kuerzel_l) or kuerzel_l in kandidat
        for kandidat in kandidaten
    )


def kader_pro_team(
    kader_rohdaten: dict[str, str],
    heimteam: str | None,
    gastteam: str | None,
) -> dict[str, dict[str, str]]:
    """
    Ordnet die beim Scraping gesammelten Kaderlisten-Texte (ein Textblock je
    angeklicktem Team-Kuerzel-Button, siehe hole_sichtbaren_text(),
    "kader_rohdaten") den beiden Mannschaften "heim"/"gast" zu und wertet
    jeden Abschnitt separat aus.

    Hauptstrategie: das Kuerzel selbst (z.B. "EHF"/"HCT") mit dem vollen
    Teamnamen abgleichen (_team_kuerzel_passt) - bestaetigt durch einen
    echten Screenshot der Seite, auf dem genau solche Kuerzel-Buttons ueber
    der Kaderliste zu sehen sind und die Tabelle zuverlaessig filtern.

    Fallback, falls KEIN Kuerzel einem Team zugeordnet werden kann (z.B. weil
    die Buttons anders beschriftet sind als angenommen): der gesamte
    gesammelte Text wird stattdessen anhand der ersten Fundstelle der vollen
    Teamnamen in zwei Abschnitte aufgeteilt. Das ist weniger praezise, aber
    besser als gar kein Kader.
    """
    ergebnis: dict[str, dict[str, str]] = {"heim": {}, "gast": {}}
    if not kader_rohdaten or not heimteam or not gastteam:
        return ergebnis

    treffer_gefunden = False
    for kuerzel, text in kader_rohdaten.items():
        for rolle, teamname in (("heim", heimteam), ("gast", gastteam)):
            if _team_kuerzel_passt(kuerzel, teamname or ""):
                kader_block = _kader_aus_text(text)
                # Falls aus Versehen zwei Kuerzel auf dieselbe Rolle zu
                # passen scheinen, wird das vollstaendigere Kader (mehr
                # erkannte Spieler) behalten.
                if len(kader_block) > len(ergebnis[rolle]):
                    ergebnis[rolle] = kader_block
                    treffer_gefunden = True
                break

    if treffer_gefunden:
        return ergebnis

    # Fallback: Text-Anker-Suche ueber den gesamten gesammelten Rohtext.
    kader_rohtext = "\n".join(kader_rohdaten.values())
    pos_heim = _erste_fundstelle(kader_rohtext, heimteam)
    pos_gast = _erste_fundstelle(kader_rohtext, gastteam)
    if pos_heim is None or pos_gast is None or pos_heim == pos_gast:
        return ergebnis

    if pos_heim < pos_gast:
        text_heim = kader_rohtext[pos_heim:pos_gast]
        text_gast = kader_rohtext[pos_gast:]
    else:
        text_gast = kader_rohtext[pos_gast:pos_heim]
        text_heim = kader_rohtext[pos_heim:]

    ergebnis["heim"] = _kader_aus_text(text_heim)
    ergebnis["gast"] = _kader_aus_text(text_gast)
    return ergebnis


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

    # Zwei unabhaengige Quellen fuer volle Spielernamen werden kombiniert:
    # (1) "#Nummer NACHNAME Vorname"-Erwaehnungen (z.B. in der Torschuetzen-
    #     liste) und (2) die Kaderliste/Boxscore-Tabelle je Team, die IMMER
    #     den vollen Vornamen zeigt, selbst wenn (1) z.B. nur abgekuerzte
    #     Vornamen liefert (siehe _baue_spieler_namen_aus_kaderliste oben).
    # Bei einem Konflikt hat die Kaderliste Vorrang, da sie die zuverlaessigere,
    # vollstaendigere Quelle ist.
    spieler_namen = {
        **_baue_spieler_namen_verzeichnis(text, text_spielverlauf),
        **_baue_spieler_namen_aus_kaderliste(text, text_spielverlauf),
    }
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
    roher_text_spielverlauf, roher_text, logos, kader_rohdaten = hole_sichtbaren_text(SPIELBERICHT_URL)
    ergebnis = parse_spielbericht(roher_text, roher_text_spielverlauf)
    kader = kader_pro_team(kader_rohdaten, ergebnis.get("heimteam"), ergebnis.get("gastteam"))

    print("----- LOGOS -----")
    print(logos)
    print("----- KADER PRO TEAM -----")
    print(kader)
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
