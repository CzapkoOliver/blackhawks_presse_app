"""
live_uebersetzer.py
--------------------
Live-Untertitel fuer Pressekonferenzen, direkt im iPad-Browser - in BEIDE Richtungen:
Englisch -> Deutsch (der Trainer spricht) und Deutsch -> Englisch (wir sprechen).

WIE ES FUNKTIONIERT:
- Der Browser kann immer nur EINE Sprache gleichzeitig erkennen. Deshalb gibt
  es zwei grosse Knoepfe: "Trainer spricht (Englisch -> Deutsch)" und "Wir
  sprechen (Deutsch -> Englisch)". Ein Tipp auf den jeweils anderen Knopf
  schaltet waehrend des Zuhoerens sofort um. Im Verlauf sind die Beitraege
  farblich und seitlich getrennt (Trainer links grau, wir rechts rot).
- Die Spracherkennung (Sprache hoeren -> Text) laeuft komplett kostenlos im
  Browser selbst (Web Speech API von Safari/iPadOS). Es wird KEIN zusaetzlicher
  Dienst/Account dafuer gebraucht.
- Nur die UEBERSETZUNG (je nach Richtung Englisch -> Deutsch oder Deutsch -> Englisch) laeuft ueber die Claude API,
  also weiterhin ausschliesslich ueber Anthropic.
- Weil Safari die Spracherkennung nach kurzen Sprechpausen automatisch beendet,
  startet das Skript sie automatisch neu ("Auto-Restart"). Dadurch fuehlt es
  sich fast durchgehend live an, auch wenn es technisch keine 100% nahtlose
  Live-Untertitelung ist (kurze Luecken von einem Bruchteil einer Sekunde
  beim Neustart sind moeglich).
- Damit ein ganzes Interview zuverlaessig komplett aufgezeichnet wird, sind
  mehrere Sicherheitsnetze eingebaut: fast jeder Fehler (Sprechpause, kurzer
  Netzwerk-Wackler) fuehrt zu einem automatischen Neustart statt zum Abbruch;
  ein "Wachhund" prueft alle paar Sekunden, ob die Erkennung noch reagiert,
  und erzwingt notfalls einen Neustart, falls sie still haengen geblieben
  ist; ein "Wake Lock" verhindert, dass der Bildschirm des iPads waehrend
  des Zuhoerens automatisch sperrt (auf neueren iPads/iOS-Versionen). Nur
  ein fehlender Mikrofon-Zugriff beendet das Zuhoeren wirklich - dann muss
  der Nutzer einmal erneut auf "Zuhoeren starten" tippen.

WICHTIGER SICHERHEITSHINWEIS:
Damit der Browser die Uebersetzung direkt bei Claude abrufen kann, ohne dass
wir dafuer einen eigenen Server bauen muessen, wird der Anthropic-API-Schluessel
in die im Browser angezeigte Seite eingebettet. Das bedeutet: Jeder, der den
Link zu deiner App kennt UND die Browser-Entwicklertools oeffnet, koennte
diesen Schluessel sehen. Fuer ein persoenliches Tool, dessen Link du nicht
oeffentlich teilst, ist das ein vertretbares Risiko - aber bitte beachte:
  1. Teile den App-Link nur mit Personen, denen du vertraust (z.B. nicht in
     einem oeffentlichen Forum posten).
  2. Setze in der Anthropic-Konsole (console.anthropic.com -> Settings ->
     Limits) ein monatliches Ausgabenlimit fuer diesen Schluessel, damit im
     schlimmsten Fall kein hoher Schaden entstehen kann.
  3. Falls du jemals den Verdacht hast, der Schluessel sei bekannt geworden,
     erstelle in der Anthropic-Konsole einen neuen Schluessel und trage ihn
     in den Streamlit-Secrets neu ein.
Der Rest der App (Pressefragen-Generator) ist davon NICHT betroffen - dort
bleibt der Schluessel wie bisher ausschliesslich auf dem Server.
"""

import json

import streamlit as st
import streamlit.components.v1 as components

# Fuer die Live-Uebersetzung wird bewusst ein schnelles, guenstiges Modell
# verwendet, da waehrend einer Pressekonferenz viele kurze Anfragen
# hintereinander gestellt werden. Falls dieses Modell in deinem Account nicht
# verfuegbar ist, unter https://docs.claude.com/en/docs/about-claude/models
# nachschauen und hier eintragen (z.B. das gleiche Modell wie in
# fragen_generator.py verwenden).
UEBERSETZER_MODELL = "claude-haiku-4-5"


def _hole_api_key() -> str | None:
    import os

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if api_key:
        return api_key
    try:
        return st.secrets.get("ANTHROPIC_API_KEY")
    except Exception:
        return None


def _baue_html(api_key: str, modell: str) -> str:
    # json.dumps sorgt dafuer, dass Anfuehrungszeichen etc. im Schluessel
    # keine Probleme im HTML/JavaScript verursachen. Die Vorlage ist bewusst
    # KEIN f-String (sonst muesste jede JavaScript-Klammer verdoppelt werden),
    # sondern nutzt zwei einfache Platzhalter.
    return (
        _HTML_VORLAGE
        .replace("__API_KEY__", json.dumps(api_key))
        .replace("__MODELL__", json.dumps(modell))
    )


_HTML_VORLAGE = r"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  /* Vereinsfarben EHF Passau Black Hawks: Schwarz, Rot, Weiss. */
  body {
    font-family: -apple-system, Arial, sans-serif;
    margin: 0;
    padding: 12px;
    background: #0d0d0d;
    color: #ffffff;
  }
  button {
    font-family: inherit;
    border-radius: 10px;
    border: 1px solid #333;
    background: #1a1a1a;
    color: #fff;
    cursor: pointer;
  }
  .steuerung {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
  }
  /* Zwei grosse Sprach-Knoepfe: der aktive ist farbig gefuellt, damit sofort
     erkennbar ist, welche Sprache gerade zugehoert wird. */
  .sprachknopf {
    flex: 1 1 220px;
    min-height: 74px;
    font-size: 18px;
    font-weight: 700;
    padding: 10px 14px;
    text-align: left;
    line-height: 1.25;
  }
  .sprachknopf span { display: block; font-size: 13px; font-weight: 500; opacity: 0.85; margin-top: 2px; }
  #btn_en { border-color: #777; }
  #btn_en.aktiv { background: #3a3f47; border-color: #b9c0cc; box-shadow: 0 0 0 2px #b9c0cc55; }
  #btn_de { border-color: #C8102E; }
  #btn_de.aktiv { background: #C8102E; border-color: #ff5a73; box-shadow: 0 0 0 2px #C8102E88; }
  #btn_stop {
    flex: 0 0 90px;
    min-height: 74px;
    font-size: 16px;
    font-weight: 600;
  }
  #btn_stop:disabled { opacity: 0.35; cursor: default; }
  .werkzeuge { margin-top: 8px; }
  .werkzeuge button {
    font-size: 13px;
    padding: 7px 12px;
    margin-right: 8px;
    margin-bottom: 6px;
  }
  .status {
    margin-top: 6px;
    font-size: 13px;
    color: #aaa;
    min-height: 18px;
  }
  .block {
    margin-top: 12px;
    padding: 10px 14px;
    border-radius: 8px;
    background: #1a1a1a;
    border: 1px solid #2a2a2a;
  }
  .block h4 {
    margin: 0 0 6px 0;
    font-size: 13px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: #C8102E;
  }
  #live_block { border-left: 4px solid #777; }
  #live_block.de { border-left-color: #C8102E; }
  #live_text { font-size: 16px; color: #ccc; min-height: 24px; }
  #verlauf { max-height: 400px; overflow-y: auto; margin-top: 12px; }

  /* Verlauf als Gespraech: Trainer (EN) links in Grau, wir (DE) rechts in
     Rot abgesetzt - so bleibt auch bei vielen Beitraegen die Uebersicht. */
  .eintrag {
    padding: 9px 12px;
    margin: 0 0 8px 0;
    border-radius: 8px;
    background: #161616;
    border: 1px solid #2a2a2a;
  }
  .eintrag.en { margin-right: 14%; border-left: 4px solid #8d96a5; }
  .eintrag.de { margin-left: 14%; border-right: 4px solid #C8102E; background: #1d1114; }
  .eintrag .kopf { display: flex; align-items: center; gap: 8px; font-size: 12px; color: #999; margin-bottom: 4px; }
  .pille { font-size: 11px; font-weight: 700; padding: 1px 7px; border-radius: 10px; color: #fff; }
  .pille.en { background: #5b6370; }
  .pille.de { background: #C8102E; }
  .eintrag .orig { color: #999; font-size: 14px; }
  .eintrag .uebers { color: #fff; font-size: 20px; font-weight: 600; margin-top: 4px; }
  .eintrag .uebers .ziel { font-size: 11px; font-weight: 700; color: #C8102E; margin-right: 6px; vertical-align: middle; }
</style>
</head>
<body>

<div class="steuerung">
  <button id="btn_en" class="sprachknopf">Trainer spricht<span>Englisch &rarr; Deutsch</span></button>
  <button id="btn_de" class="sprachknopf">Wir sprechen<span>Deutsch &rarr; Englisch</span></button>
  <button id="btn_stop" disabled>Stopp</button>
</div>
<div class="status" id="status">Bereit. Oben die Sprache waehlen, die gerade gesprochen wird.</div>

<div class="werkzeuge">
  <button id="reset">Verlauf loeschen</button>
  <button id="download_btn">Transkript herunterladen (.txt)</button>
  <button id="email_btn">Per E-Mail senden</button>
</div>

<div class="block" id="live_block">
  <h4 id="live_titel">Gerade gehoert</h4>
  <div id="live_text">...</div>
</div>

<div id="verlauf"></div>

<div class="block">
  <h4>Transkript als Text (zum manuellen Kopieren, falls Download/E-Mail nicht klappt)</h4>
  <textarea id="transkript_textfeld" readonly rows="4"
    style="width:100%; box-sizing:border-box; background:#0e1117; color:#ccc; border:1px solid #333; border-radius:6px; padding:8px; font-family:monospace; font-size:12px;">(Noch keine Aeusserungen aufgezeichnet.)</textarea>
</div>

<script>
const API_KEY = __API_KEY__;
const MODELL = __MODELL__;

// Beide Richtungen an einer Stelle. "kurz" = Sprachkuerzel fuer Anzeige und
// Transkript, "sprecher" = wer gerade spricht.
const RICHTUNGEN = {
  en: {
    code: "en-US", name: "Englisch", kurz: "EN", sprecher: "Trainer",
    zielKurz: "DE", zielName: "Deutsch",
    prompt: function(t) {
      return "Uebersetze den folgenden englischen Satz eines Eishockeytrainers exakt und natuerlich ins Deutsche. Gib NUR die deutsche Uebersetzung zurueck, ohne Anfuehrungszeichen, ohne Erklaerung, ohne Vor- oder Nachsatz.\n\nSatz: " + t;
    }
  },
  de: {
    code: "de-DE", name: "Deutsch", kurz: "DE", sprecher: "Wir",
    zielKurz: "EN", zielName: "Englisch",
    prompt: function(t) {
      return "Translate the following German sentence, spoken at an ice hockey press conference by the club's press officer or a journalist, exactly and naturally into English. Return ONLY the English translation, without quotation marks, explanation, or any preface or afterword.\n\nSentence: " + t;
    }
  }
};

const btnEn = document.getElementById("btn_en");
const btnDe = document.getElementById("btn_de");
const btnStop = document.getElementById("btn_stop");
const resetBtn = document.getElementById("reset");
const downloadBtn = document.getElementById("download_btn");
const emailBtn = document.getElementById("email_btn");
const statusEl = document.getElementById("status");
const liveBlockEl = document.getElementById("live_block");
const liveTitelEl = document.getElementById("live_titel");
const liveTextEl = document.getElementById("live_text");
const verlaufEl = document.getElementById("verlauf");
const transkriptFeldEl = document.getElementById("transkript_textfeld");

let sollLaufen = false;
let recognition = null;
// Gewuenschte Sprache (per Knopf gewaehlt) und die Sprache, mit der die
// AKTUELLE Erkennungs-Sitzung tatsaechlich gestartet wurde. Ergebnisse
// werden immer der Sitzungs-Sprache zugeordnet - so wird ein Satz, der
// gerade beim Umschalten noch fertig erkannt wird, nicht falsch beschriftet.
let modus = "en";
let sitzungModus = "en";
// Chronologisch (aeltester Eintrag zuerst) fuer das Transkript, unabhaengig
// davon, dass die Anzeige oben die neuesten Eintraege zuerst zeigt.
let verlaufDaten = [];
let wakeLock = null;
// Zeitpunkt des letzten Lebenszeichens der Spracherkennung. Der Wachhund
// unten nutzt das, um einen "stillen" Ausfall zu erkennen (kommt auf iOS
// gelegentlich vor, z.B. wenn das iPad kurz einschlaeft).
let letzteAktivitaet = Date.now();
let wachhundTimer = null;

const SpeechRecognitionKlasse = window.SpeechRecognition || window.webkitSpeechRecognition;

function aktualisiereAnzeige() {
  btnEn.classList.toggle("aktiv", sollLaufen && modus === "en");
  btnDe.classList.toggle("aktiv", sollLaufen && modus === "de");
  btnStop.disabled = !sollLaufen;
  liveBlockEl.classList.toggle("de", sitzungModus === "de");
  liveTitelEl.textContent = "Gerade gehoert (" + RICHTUNGEN[sitzungModus].name + ", live)";
}

if (!SpeechRecognitionKlasse) {
  statusEl.textContent = "Spracherkennung wird von diesem Browser leider nicht unterstuetzt. Bitte Safari auf dem iPad verwenden.";
  btnEn.disabled = true;
  btnDe.disabled = true;
} else {
  recognition = new SpeechRecognitionKlasse();
  recognition.continuous = true;
  recognition.interimResults = true;

  // NUR diese beiden Fehler bedeuten "der Nutzer muss etwas tun" -> in
  // jedem anderen Fall wird automatisch weiterversucht, damit das Interview
  // nie wegen einer kurzen Stoerung abbricht.
  const ENDGUELTIGE_FEHLER = ["not-allowed", "service-not-allowed"];

  recognition.onstart = function() {
    letzteAktivitaet = Date.now();
    statusEl.textContent = "Hoert zu ... (" + RICHTUNGEN[sitzungModus].name + ")";
  };

  recognition.onerror = function(event) {
    letzteAktivitaet = Date.now();
    if (ENDGUELTIGE_FEHLER.includes(event.error)) {
      statusEl.textContent = "Mikrofon-Zugriff wurde nicht erlaubt. Bitte in den iPad-Einstellungen fuer diese Seite erlauben und erneut auf einen der Sprach-Knoepfe tippen.";
      sollLaufen = false;
      aktualisiereAnzeige();
      stoppeWachhund();
      gibWakeLockFrei();
    } else {
      // z.B. "no-speech", "audio-capture", "network" oder "aborted" - das
      // sind normale, voruebergehende Stoerungen. Der Neustart passiert in
      // onend, hier nur die Statusanzeige.
      statusEl.textContent = "Kurze Unterbrechung (" + event.error + ") - startet automatisch neu ...";
    }
  };

  recognition.onend = function() {
    letzteAktivitaet = Date.now();
    if (sollLaufen) {
      // Safari beendet die Erkennung nach kurzen Pausen von selbst - und
      // auch beim Umschalten der Sprache wird hier mit der NEUEN Sprache
      // neu gestartet (siehe starteErkennung).
      versucheNeustart();
    } else {
      statusEl.textContent = "Gestoppt.";
    }
  };

  recognition.onresult = function(event) {
    letzteAktivitaet = Date.now();
    let interimText = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const ergebnis = event.results[i];
      if (ergebnis.isFinal) {
        const finalerText = ergebnis[0].transcript.trim();
        if (finalerText.length > 0) {
          liveTextEl.textContent = "...";
          uebersetzeUndZeige(finalerText, sitzungModus);
        }
      } else {
        interimText += ergebnis[0].transcript;
      }
    }
    if (interimText) {
      liveTextEl.textContent = interimText;
    }
  };
}

// Startet die Erkennung in der aktuell gewaehlten Sprache.
function starteErkennung() {
  sitzungModus = modus;
  recognition.lang = RICHTUNGEN[modus].code;
  aktualisiereAnzeige();
  recognition.start();
  letzteAktivitaet = Date.now();
}

function versucheNeustart(versuch) {
  versuch = versuch || 1;
  if (!sollLaufen) return;
  const wartezeit = Math.min(250 * versuch, 2000);
  setTimeout(function() {
    if (!sollLaufen) return;
    try {
      starteErkennung();
    } catch (e) {
      // "laeuft schon" oder aehnliches - notfalls weiter versuchen, damit
      // nie stillschweigend aufgehoert wird zuzuhoeren.
      if (versuch < 8) {
        versucheNeustart(versuch + 1);
      }
    }
  }, wartezeit);
}

function starteWachhund() {
  stoppeWachhund();
  wachhundTimer = setInterval(function() {
    if (!sollLaufen) return;
    const ruhezeit = Date.now() - letzteAktivitaet;
    // 12 Sekunden ganz ohne Lebenszeichen heisst: die Erkennung ist still
    // haengengeblieben. Dann hart neu starten.
    if (ruhezeit > 12000) {
      statusEl.textContent = "Keine Reaktion erkannt - starte Spracherkennung neu ...";
      try { recognition.stop(); } catch (e) {}
      try { recognition.abort(); } catch (e) {}
      letzteAktivitaet = Date.now();
      versucheNeustart();
    }
  }, 4000);
}

function stoppeWachhund() {
  if (wachhundTimer) {
    clearInterval(wachhundTimer);
    wachhundTimer = null;
  }
}

async function holeWakeLock() {
  try {
    if ("wakeLock" in navigator) {
      wakeLock = await navigator.wakeLock.request("screen");
    }
  } catch (e) {
    // Nicht unterstuetzt oder abgelehnt - dann bitte manuell darauf achten,
    // dass der Bildschirm nicht automatisch sperrt.
  }
}

function gibWakeLockFrei() {
  if (wakeLock) {
    try { wakeLock.release(); } catch (e) {}
    wakeLock = null;
  }
}

// Kommt die Seite kurz in den Hintergrund und wieder zurueck, sicherheits-
// halber pruefen, ob die Erkennung noch laeuft.
document.addEventListener("visibilitychange", function() {
  if (document.visibilityState === "visible" && sollLaufen) {
    holeWakeLock();
    versucheNeustart();
  }
});

function maskiere(text) {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;");
}

async function uebersetzeUndZeige(originalText, m) {
  const r = RICHTUNGEN[m];
  const zeit = new Date();
  const eintrag = document.createElement("div");
  eintrag.className = "eintrag " + m;
  eintrag.innerHTML =
    '<div class="kopf"><span class="pille ' + m + '">' + r.kurz + '</span>' +
    '<span>' + r.sprecher + ' &middot; ' + zeit.toLocaleTimeString("de-DE") + '</span></div>' +
    '<div class="orig">' + maskiere(originalText) + '</div>' +
    '<div class="uebers"><span class="ziel">' + r.zielKurz + '</span><span class="text">Uebersetze ...</span></div>';
  verlaufEl.prepend(eintrag);
  const textEl = eintrag.querySelector(".uebers .text");

  const transkriptEintrag = { zeit: zeit, modus: m, original: originalText, uebersetzung: "" };
  verlaufDaten.push(transkriptEintrag);

  try {
    const antwort = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-api-key": API_KEY,
        "anthropic-version": "2023-06-01",
        "anthropic-dangerous-direct-browser-access": "true"
      },
      body: JSON.stringify({
        model: MODELL,
        max_tokens: 300,
        messages: [{ role: "user", content: r.prompt(originalText) }]
      })
    });

    if (!antwort.ok) {
      const fehlerText = await antwort.text();
      textEl.textContent = "Fehler bei der Uebersetzung (" + antwort.status + ")";
      statusEl.textContent = "Claude-Fehler: " + fehlerText.substring(0, 200);
      transkriptEintrag.uebersetzung = "(Fehler bei der Uebersetzung)";
      transkriptFeldEl.value = baueTranskriptText();
      return;
    }

    const daten = await antwort.json();
    const textBloecke = (daten.content || []).filter(b => b.type === "text").map(b => b.text);
    const uebersetzung = textBloecke.join(" ").trim() || "(keine Uebersetzung erhalten)";
    textEl.textContent = uebersetzung;
    transkriptEintrag.uebersetzung = uebersetzung;
  } catch (e) {
    textEl.textContent = "Fehler bei der Uebersetzung (Netzwerk).";
    statusEl.textContent = "Fehler: " + e;
    transkriptEintrag.uebersetzung = "(Fehler bei der Uebersetzung)";
  }
  transkriptFeldEl.value = baueTranskriptText();
}

function baueTranskriptText() {
  const jetzt = new Date();
  const kopf = "Pressekonferenz-Transkript - erstellt am " + jetzt.toLocaleDateString("de-DE") + " um " + jetzt.toLocaleTimeString("de-DE") + "\n" + "=".repeat(60) + "\n\n";
  if (verlaufDaten.length === 0) {
    return kopf + "(Noch keine Aeusserungen aufgezeichnet.)";
  }
  const abschnitte = verlaufDaten.map(function(eintrag, i) {
    const r = RICHTUNGEN[eintrag.modus];
    const zeitStr = eintrag.zeit.toLocaleTimeString("de-DE");
    return (i + 1) + ". [" + zeitStr + "] " + r.sprecher + "\n" +
      r.kurz + ": " + eintrag.original + "\n" +
      r.zielKurz + ": " + (eintrag.uebersetzung || "(keine Uebersetzung)");
  });
  return kopf + abschnitte.join("\n\n");
}

function herunterladen() {
  const text = baueTranskriptText();
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  const zeitstempel = new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-");
  link.href = url;
  link.download = "pressekonferenz-transkript-" + zeitstempel + ".txt";
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

function perEmailSenden() {
  const text = baueTranskriptText();
  const betreff = "Transkript Pressekonferenz " + new Date().toLocaleDateString("de-DE");
  // E-Mail-Programme haben ein Laengenlimit fuer mailto-Links. Bei laengeren
  // Transkripten wird deshalb gekuerzt - fuer den vollstaendigen Text
  // stattdessen "Transkript herunterladen" nutzen.
  const MAX_LAENGE = 1800;
  let koerper = text;
  if (koerper.length > MAX_LAENGE) {
    koerper = koerper.substring(0, MAX_LAENGE) +
      "\n\n[... Transkript wurde fuer die E-Mail gekuerzt. Vollstaendige Version bitte ueber 'Transkript herunterladen' als Datei anhaengen.]";
  }
  window.location.href = "mailto:?subject=" + encodeURIComponent(betreff) + "&body=" + encodeURIComponent(koerper);
}

// Sprach-Knopf: startet das Zuhoeren in dieser Sprache bzw. schaltet waehrend
// des Zuhoerens sofort auf diese Sprache um.
function waehleSprache(neuerModus) {
  if (!recognition) return;
  if (!sollLaufen) {
    modus = neuerModus;
    sollLaufen = true;
    try { starteErkennung(); } catch (e) { /* evtl. schon gestartet */ }
    holeWakeLock();
    starteWachhund();
  } else if (modus !== neuerModus) {
    modus = neuerModus;
    statusEl.textContent = "Wechsle auf " + RICHTUNGEN[modus].name + " ...";
    // Beenden loest onend aus; dort wird mit der neuen Sprache neu gestartet.
    try { recognition.stop(); } catch (e) {}
  }
  aktualisiereAnzeige();
}

btnEn.addEventListener("click", function() { waehleSprache("en"); });
btnDe.addEventListener("click", function() { waehleSprache("de"); });

btnStop.addEventListener("click", function() {
  if (!recognition || !sollLaufen) return;
  sollLaufen = false;
  aktualisiereAnzeige();
  try { recognition.stop(); } catch (e) {}
  stoppeWachhund();
  gibWakeLockFrei();
});

resetBtn.addEventListener("click", function() {
  verlaufEl.innerHTML = "";
  liveTextEl.textContent = "...";
  verlaufDaten = [];
  transkriptFeldEl.value = "(Noch keine Aeusserungen aufgezeichnet.)";
});

downloadBtn.addEventListener("click", herunterladen);
emailBtn.addEventListener("click", perEmailSenden);
aktualisiereAnzeige();
</script>
</body>
</html>
"""


def render() -> None:
    """
    Zeigt die Live-Uebersetzer-Komponente in der Streamlit-App an.
    Einfach in app.py aufrufen mit: live_uebersetzer.render()
    """
    api_key = _hole_api_key()
    if not api_key:
        st.warning(
            "Kein API-Schluessel gefunden. Lokal: in der Datei .env die Zeile "
            "ANTHROPIC_API_KEY=dein-schluessel eintragen. Online: in den "
            "Streamlit-Cloud-App-Einstellungen unter 'Secrets' hinterlegen."
        )
        return

    st.caption(
        "Zuerst die gesprochene Sprache waehlen: \"Trainer spricht\" (Englisch -> Deutsch) oder \"Wir sprechen\" (Deutsch -> Englisch); ein Tipp auf den anderen Knopf schaltet um. Mikrofon-Zugriff erlauben, sobald Safari danach fragt. Funktioniert am "
        "zuverlaessigsten in Safari auf dem iPad (nicht Chrome/Firefox). Diese "
        "Browser-Unterseite (Tab) waehrend des ganzen Interviews aktiv/vorne "
        "lassen und nicht die App wechseln - am sichersten zusaetzlich die "
        "automatische Bildschirmsperre des iPads fuer die Dauer der "
        "Pressekonferenz kurz deaktivieren (Einstellungen > Anzeige & "
        "Helligkeit > Automatische Sperre > 'Nie')."
    )
    components.html(_baue_html(api_key, UEBERSETZER_MODELL), height=780, scrolling=True)
