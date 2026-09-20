"""
live_uebersetzer.py
--------------------
Live-Untertitel Englisch -> Deutsch fuer Pressekonferenzen, direkt im iPad-Browser.

WIE ES FUNKTIONIERT:
- Die Spracherkennung (Englisch hoeren -> Text) laeuft komplett kostenlos im
  Browser selbst (Web Speech API von Safari/iPadOS). Es wird KEIN zusaetzlicher
  Dienst/Account dafuer gebraucht.
- Nur die UEBERSETZUNG (Englisch-Text -> Deutsch) laeuft ueber die Claude API,
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
    # keine Probleme im HTML/JavaScript verursachen.
    api_key_js = json.dumps(api_key)
    modell_js = json.dumps(modell)

    return f"""
<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<style>
  /* Vereinsfarben EHF Passau Black Hawks: Schwarz, Rot, Weiss. */
  body {{
    font-family: -apple-system, Arial, sans-serif;
    margin: 0;
    padding: 12px;
    background: #0d0d0d;
    color: #ffffff;
  }}
  button {{
    font-size: 18px;
    padding: 10px 20px;
    border-radius: 8px;
    border: 1px solid transparent;
    margin-right: 10px;
    margin-bottom: 8px;
    cursor: pointer;
  }}
  #start_stop {{
    background: #C8102E;
    color: white;
  }}
  #start_stop.laeuft {{
    background: #0d0d0d;
    color: #ffffff;
    border: 1px solid #C8102E;
  }}
  #reset, #download_btn, #email_btn {{
    background: #1a1a1a;
    color: white;
    border: 1px solid #333;
    font-size: 14px;
    padding: 8px 14px;
  }}
  .status {{
    margin-top: 8px;
    font-size: 13px;
    color: #aaa;
  }}
  .block {{
    margin-top: 14px;
    padding: 10px 14px;
    border-radius: 8px;
    background: #1a1a1a;
    border: 1px solid #2a2a2a;
  }}
  .block h4 {{
    margin: 0 0 6px 0;
    font-size: 13px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: #C8102E;
  }}
  #englisch_live {{
    font-size: 16px;
    color: #ccc;
    min-height: 24px;
  }}
  #verlauf {{
    max-height: 380px;
    overflow-y: auto;
    margin-top: 14px;
  }}
  .eintrag {{
    padding: 10px 0;
    border-bottom: 1px solid #2a2a2a;
  }}
  .eintrag .en {{
    color: #999;
    font-size: 14px;
  }}
  .eintrag .de {{
    color: #ffffff;
    font-size: 20px;
    font-weight: 600;
    margin-top: 4px;
  }}
</style>
</head>
<body>

<button id="start_stop">Zuhoeren starten</button>
<button id="reset">Verlauf loeschen</button>
<button id="download_btn">Transkript herunterladen (.txt)</button>
<button id="email_btn">Per E-Mail senden</button>
<div class="status" id="status">Bereit.</div>

<div class="block">
  <h4>Gerade gehoert (Englisch, live)</h4>
  <div id="englisch_live">...</div>
</div>

<div id="verlauf"></div>

<div class="block">
  <h4>Transkript als Text (zum manuellen Kopieren, falls Download/E-Mail nicht klappt)</h4>
  <textarea id="transkript_textfeld" readonly rows="4"
    style="width:100%; box-sizing:border-box; background:#0e1117; color:#ccc; border:1px solid #333; border-radius:6px; padding:8px; font-family:monospace; font-size:12px;">(Noch keine Aeusserungen aufgezeichnet.)</textarea>
</div>

<script>
const API_KEY = {api_key_js};
const MODELL = {modell_js};

const startStopBtn = document.getElementById("start_stop");
const resetBtn = document.getElementById("reset");
const downloadBtn = document.getElementById("download_btn");
const emailBtn = document.getElementById("email_btn");
const statusEl = document.getElementById("status");
const englischLiveEl = document.getElementById("englisch_live");
const verlaufEl = document.getElementById("verlauf");
const transkriptFeldEl = document.getElementById("transkript_textfeld");

let sollLaufen = false;
let recognition = null;
// Chronologisch (aeltester Eintrag zuerst) fuer das Transkript, unabhaengig
// davon, dass die Anzeige oben die neuesten Eintraege zuerst zeigt.
let verlaufDaten = [];
let wakeLock = null;
// Zeitpunkt des letzten Lebenszeichens der Spracherkennung (Start, Ergebnis,
// Fehler oder Ende). Der Wachhund unten nutzt das, um einen "stillen"
// Ausfall zu erkennen, bei dem weder onend noch onerror ausgeloest wird -
// das kommt auf iOS gelegentlich vor, z.B. wenn das iPad kurz einschlaeft.
let letzteAktivitaet = Date.now();
let wachhundTimer = null;

const SpeechRecognitionKlasse = window.SpeechRecognition || window.webkitSpeechRecognition;

if (!SpeechRecognitionKlasse) {{
  statusEl.textContent = "Spracherkennung wird von diesem Browser leider nicht unterstuetzt. Bitte Safari auf dem iPad verwenden.";
  startStopBtn.disabled = true;
}} else {{
  recognition = new SpeechRecognitionKlasse();
  recognition.lang = "en-US";
  recognition.continuous = true;
  recognition.interimResults = true;

  // NUR diese beiden Fehler bedeuten "der Nutzer muss etwas tun" -> in
  // jedem anderen Fall wird automatisch weiterversucht, damit das Interview
  // nie wegen einer kurzen Stoerung abbricht.
  const ENDGUELTIGE_FEHLER = ["not-allowed", "service-not-allowed"];

  recognition.onstart = function() {{
    letzteAktivitaet = Date.now();
    statusEl.textContent = "Hoert zu ... (Englisch)";
  }};

  recognition.onerror = function(event) {{
    letzteAktivitaet = Date.now();
    if (ENDGUELTIGE_FEHLER.includes(event.error)) {{
      statusEl.textContent = "Mikrofon-Zugriff wurde nicht erlaubt. Bitte in den iPad-Einstellungen fuer diese Seite erlauben und erneut auf 'Zuhoeren starten' tippen.";
      sollLaufen = false;
      startStopBtn.classList.remove("laeuft");
      startStopBtn.textContent = "Zuhoeren starten";
      stoppeWachhund();
      gibWakeLockFrei();
    }} else {{
      // z.B. "no-speech", "audio-capture", "network" oder "aborted" - das
      // sind normale, voruebergehende Stoerungen (Sprechpause, kurzer
      // Wackler). Der Neustart passiert in onend, hier nur Statusanzeige.
      statusEl.textContent = "Kurze Unterbrechung (" + event.error + ") - startet automatisch neu ...";
    }}
  }};

  recognition.onend = function() {{
    letzteAktivitaet = Date.now();
    if (sollLaufen) {{
      // Safari beendet die Erkennung nach kurzen Pausen von selbst.
      // Deshalb hier automatisch neu starten, solange der Nutzer nicht
      // selbst auf "Stopp" gedrueckt hat. Mehrere Versuche mit steigendem
      // Abstand, falls der erste Neustart-Versuch zu frueh kommt.
      versucheNeustart();
    }} else {{
      statusEl.textContent = "Gestoppt.";
    }}
  }};

  recognition.onresult = function(event) {{
    letzteAktivitaet = Date.now();
    let interimText = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {{
      const ergebnis = event.results[i];
      if (ergebnis.isFinal) {{
        const finalerText = ergebnis[0].transcript.trim();
        if (finalerText.length > 0) {{
          englischLiveEl.textContent = "...";
          uebersetzeUndZeige(finalerText);
        }}
      }} else {{
        interimText += ergebnis[0].transcript;
      }}
    }}
    if (interimText) {{
      englischLiveEl.textContent = interimText;
    }}
  }};
}}

function versucheNeustart(versuch) {{
  versuch = versuch || 1;
  if (!sollLaufen) return;
  const wartezeit = Math.min(250 * versuch, 2000);
  setTimeout(function() {{
    if (!sollLaufen) return;
    try {{
      recognition.start();
      letzteAktivitaet = Date.now();
    }} catch (e) {{
      // "laeuft schon" oder aehnliches - notfalls weiter versuchen, damit
      // nie stillschweigend aufgehoert wird zuzuhoeren.
      if (versuch < 8) {{
        versucheNeustart(versuch + 1);
      }}
    }}
  }}, wartezeit);
}}

function starteWachhund() {{
  stoppeWachhund();
  wachhundTimer = setInterval(function() {{
    if (!sollLaufen) return;
    const ruhezeit = Date.now() - letzteAktivitaet;
    // 12 Sekunden ganz ohne jedes Lebenszeichen (kein Start, Ergebnis,
    // Fehler oder Ende) heisst: die Erkennung ist still haengengeblieben,
    // z.B. weil das iPad kurz eingeschlafen ist. Dann hart neu starten.
    if (ruhezeit > 12000) {{
      statusEl.textContent = "Keine Reaktion erkannt - starte Spracherkennung neu ...";
      try {{ recognition.stop(); }} catch (e) {{}}
      try {{ recognition.abort(); }} catch (e) {{}}
      letzteAktivitaet = Date.now();
      versucheNeustart();
    }}
  }}, 4000);
}}

function stoppeWachhund() {{
  if (wachhundTimer) {{
    clearInterval(wachhundTimer);
    wachhundTimer = null;
  }}
}}

async function holeWakeLock() {{
  try {{
    if ("wakeLock" in navigator) {{
      wakeLock = await navigator.wakeLock.request("screen");
    }}
  }} catch (e) {{
    // Nicht unterstuetzt oder abgelehnt - kein Problem, aber dann bitte
    // manuell darauf achten, dass der Bildschirm nicht automatisch sperrt.
  }}
}}

function gibWakeLockFrei() {{
  if (wakeLock) {{
    try {{ wakeLock.release(); }} catch (e) {{}}
    wakeLock = null;
  }}
}}

// Falls die Seite kurz in den Hintergrund geht (App-Wechsel, Bildschirm
// kurz aus) und wieder sichtbar wird, sicherheitshalber pruefen, ob die
// Erkennung noch laeuft, und sonst neu anstossen.
document.addEventListener("visibilitychange", function() {{
  if (document.visibilityState === "visible" && sollLaufen) {{
    holeWakeLock();
    versucheNeustart();
  }}
}});

async function uebersetzeUndZeige(englischerText) {{
  const eintrag = document.createElement("div");
  eintrag.className = "eintrag";
  eintrag.innerHTML = '<div class="en">' + englischerText.replace(/</g, "&lt;") + '</div><div class="de">Uebersetze ...</div>';
  verlaufEl.prepend(eintrag);
  const deEl = eintrag.querySelector(".de");

  const transkriptEintrag = {{ zeit: new Date(), en: englischerText, de: "" }};
  verlaufDaten.push(transkriptEintrag);

  try {{
    const antwort = await fetch("https://api.anthropic.com/v1/messages", {{
      method: "POST",
      headers: {{
        "content-type": "application/json",
        "x-api-key": API_KEY,
        "anthropic-version": "2023-06-01",
        "anthropic-dangerous-direct-browser-access": "true"
      }},
      body: JSON.stringify({{
        model: MODELL,
        max_tokens: 300,
        messages: [{{
          role: "user",
          content: "Uebersetze den folgenden englischen Satz eines Eishockeytrainers exakt und natuerlich ins Deutsche. Gib NUR die deutsche Uebersetzung zurueck, ohne Anfuehrungszeichen, ohne Erklaerung, ohne Vor- oder Nachsatz.\\n\\nSatz: " + englischerText
        }}]
      }})
    }});

    if (!antwort.ok) {{
      const fehlerText = await antwort.text();
      deEl.textContent = "Fehler bei der Uebersetzung (" + antwort.status + ")";
      statusEl.textContent = "Claude-Fehler: " + fehlerText.substring(0, 200);
      return;
    }}

    const daten = await antwort.json();
    const textBloecke = (daten.content || []).filter(b => b.type === "text").map(b => b.text);
    const uebersetzung = textBloecke.join(" ").trim() || "(keine Uebersetzung erhalten)";
    deEl.textContent = uebersetzung;
    transkriptEintrag.de = uebersetzung;
  }} catch (e) {{
    deEl.textContent = "Fehler bei der Uebersetzung (Netzwerk).";
    statusEl.textContent = "Fehler: " + e;
    transkriptEintrag.de = "(Fehler bei der Uebersetzung)";
  }}
  transkriptFeldEl.value = baueTranskriptText();
}}

function baueTranskriptText() {{
  const jetzt = new Date();
  const kopf = "Pressekonferenz-Transkript - erstellt am " + jetzt.toLocaleDateString("de-DE") + " um " + jetzt.toLocaleTimeString("de-DE") + "\\n" + "=".repeat(60) + "\\n\\n";
  if (verlaufDaten.length === 0) {{
    return kopf + "(Noch keine Aeusserungen aufgezeichnet.)";
  }}
  const abschnitte = verlaufDaten.map(function(eintrag, i) {{
    const zeitStr = eintrag.zeit.toLocaleTimeString("de-DE");
    return (i + 1) + ". [" + zeitStr + "]\\nEN: " + eintrag.en + "\\nDE: " + (eintrag.de || "(keine Uebersetzung)");
  }});
  return kopf + abschnitte.join("\\n\\n");
}}

function herunterladen() {{
  const text = baueTranskriptText();
  const blob = new Blob([text], {{ type: "text/plain;charset=utf-8" }});
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  const zeitstempel = new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-");
  link.href = url;
  link.download = "pressekonferenz-transkript-" + zeitstempel + ".txt";
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}}

function perEmailSenden() {{
  const text = baueTranskriptText();
  const betreff = "Transkript Pressekonferenz " + new Date().toLocaleDateString("de-DE");
  // E-Mail-Programme haben ein Laengenlimit fuer mailto-Links (meist ca.
  // 1800-2000 Zeichen sind sicher plattformuebergreifend). Bei laengeren
  // Transkripten wird deshalb gekuerzt und ein Hinweis ergaenzt - fuer den
  // vollstaendigen Text bitte stattdessen "Transkript herunterladen" nutzen
  // und die Datei manuell an eine E-Mail anhaengen.
  const MAX_LAENGE = 1800;
  let koerper = text;
  let gekuerzt = false;
  if (koerper.length > MAX_LAENGE) {{
    koerper = koerper.substring(0, MAX_LAENGE);
    gekuerzt = true;
  }}
  if (gekuerzt) {{
    koerper += "\\n\\n[... Transkript wurde fuer die E-Mail gekuerzt. Vollstaendige Version bitte ueber 'Transkript herunterladen' als Datei anhaengen.]";
  }}
  const mailtoLink = "mailto:?subject=" + encodeURIComponent(betreff) + "&body=" + encodeURIComponent(koerper);
  window.location.href = mailtoLink;
}}

startStopBtn.addEventListener("click", function() {{
  if (!recognition) return;
  if (!sollLaufen) {{
    sollLaufen = true;
    letzteAktivitaet = Date.now();
    startStopBtn.classList.add("laeuft");
    startStopBtn.textContent = "Zuhoeren stoppen";
    try {{ recognition.start(); }} catch (e) {{ /* evtl. schon gestartet */ }}
    holeWakeLock();
    starteWachhund();
  }} else {{
    sollLaufen = false;
    startStopBtn.classList.remove("laeuft");
    startStopBtn.textContent = "Zuhoeren starten";
    try {{ recognition.stop(); }} catch (e) {{}}
    stoppeWachhund();
    gibWakeLockFrei();
  }}
}});

resetBtn.addEventListener("click", function() {{
  verlaufEl.innerHTML = "";
  englischLiveEl.textContent = "...";
  verlaufDaten = [];
  transkriptFeldEl.value = "(Noch keine Aeusserungen aufgezeichnet.)";
}});

downloadBtn.addEventListener("click", herunterladen);
emailBtn.addEventListener("click", perEmailSenden);
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
        "Mikrofon-Zugriff erlauben, sobald Safari danach fragt. Funktioniert am "
        "zuverlaessigsten in Safari auf dem iPad (nicht Chrome/Firefox). Diese "
        "Browser-Unterseite (Tab) waehrend des ganzen Interviews aktiv/vorne "
        "lassen und nicht die App wechseln - am sichersten zusaetzlich die "
        "automatische Bildschirmsperre des iPads fuer die Dauer der "
        "Pressekonferenz kurz deaktivieren (Einstellungen > Anzeige & "
        "Helligkeit > Automatische Sperre > 'Nie')."
    )
    components.html(_baue_html(api_key, UEBERSETZER_MODELL), height=780, scrolling=True)
