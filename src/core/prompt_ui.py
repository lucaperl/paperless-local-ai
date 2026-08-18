import json
import os
import traceback

import requests
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from app_config import (
    config_hash as app_config_hash,
    ensure_config as ensure_app_config,
    list_history as list_app_history,
    restore_history as restore_app_history,
    save_config as save_app_config,
    validate_config as validate_app_config,
)

from prompt_runtime import (
    PLACEHOLDERS,
    PaperlessClient,
    ai_resource_lock,
    call_ollama,
    ensure_config,
    list_history,
    load_config,
    make_schema,
    performance_from_raw,
    prompt_hashes,
    render_prompts,
    restore_history,
    save_config,
    validate_config,
    validate_result,
)
from correspondent_runtime import (
    PLACEHOLDERS as CORRESPONDENT_PLACEHOLDERS,
    call_ollama as call_correspondent_ollama,
    ensure_config as ensure_correspondent_config,
    list_history as list_correspondent_history,
    performance_from_raw as correspondent_performance_from_raw,
    prompt_hashes as correspondent_prompt_hashes,
    render_prompts as render_correspondent_prompts,
    restore_history as restore_correspondent_history,
    save_config as save_correspondent_config,
    validate_config as validate_correspondent_config,
    validate_result as validate_correspondent_result,
)

HOST = os.getenv("PROMPT_UI_HOST", "0.0.0.0")
PORT = int(os.getenv("PROMPT_UI_PORT", "8080"))
client = PaperlessClient()
PAPERLESS_TOKEN = os.environ.get("PAPERLESS_TOKEN", "")


HTML = r'''<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>paperless-local-ai Studio</title>
<style>
:root{color-scheme:dark;--bg:#0f1115;--panel:#171a21;--panel2:#13171e;--line:#2a2f3a;--text:#e8eaf0;--muted:#9ca3af;--accent:#79a7ff;--accent-bg:#1c2940;--ok:#76d49b;--bad:#ff8b8b;--warn:#e8c273}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}
header{padding:18px 24px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center;gap:16px;background:#101319}h1{font-size:20px;margin:0}h2{font-size:17px;margin:0 0 8px}h3{font-size:15px;margin:0 0 10px}main{padding:20px;max-width:1500px;margin:auto}
.mode-switch{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:20px}.mode-switch button{text-align:left;background:var(--panel2);border:1px solid var(--line);padding:15px 17px;border-radius:10px}.mode-switch button.active{background:var(--accent-bg);border-color:#466697}.mode-title{display:block;font-size:16px;font-weight:650;margin-bottom:3px}.mode-desc{display:block;color:var(--muted);font-size:12px;font-weight:400}
.mode{display:none}.mode.active{display:block}.mode-head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:14px}.mode-head p{margin:4px 0 0;color:var(--muted);max-width:980px}.config-badge{white-space:nowrap;padding:7px 10px;border-radius:7px;background:#202530;border:1px solid var(--line);color:var(--accent);font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px}
.actionbar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin-bottom:12px}.actionbar .status{margin-left:auto;min-width:260px}
.subtabs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:16px;padding-bottom:10px;border-bottom:1px solid var(--line)}.subtabs button{background:transparent;border:1px solid transparent}.subtabs button:hover{background:#1b2028}.subtabs button.active{background:#273044;border-color:#38465f}.subtab-page{display:none}.subtab-page.active{display:block}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}.full{grid-column:1/-1}
textarea,input,select{width:100%;background:#0d1015;border:1px solid var(--line);color:var(--text);border-radius:7px;padding:9px;font:13px/1.45 ui-monospace,SFMono-Regular,Consolas,monospace}textarea{min-height:280px;resize:vertical}.smallarea{min-height:150px}
button{border:0;border-radius:7px;background:#2c3340;color:var(--text);padding:9px 14px;cursor:pointer}button.primary{background:#315ea8}button.danger{background:#7a3434}button:disabled{opacity:.45;cursor:not-allowed}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.row>*{flex:1}.row button,.row label{flex:0 0 auto}.muted{color:var(--muted)}.help{color:var(--muted);margin:6px 0 0;max-width:1100px}.intro{background:#141923;border:1px solid var(--line);border-left:3px solid var(--accent);border-radius:8px;padding:11px 13px;margin:0 0 16px}.intro strong{color:var(--text)}.field-help{color:var(--muted);font-size:12px;line-height:1.4;margin-top:5px}
.placeholder-grid{display:grid;grid-template-columns:repeat(2,minmax(280px,1fr));gap:8px;margin-top:10px}.placeholder-item{background:#11151c;border:1px solid var(--line);border-radius:7px;padding:9px}.placeholder-item code{display:block;color:var(--accent);font-size:12px;margin-bottom:4px}.placeholder-item span{color:var(--muted);font-size:12px}
.status{padding:8px 12px;border-radius:7px;background:#202530;white-space:pre-wrap}.status.ok{color:var(--ok)}.status.bad{color:var(--bad)}pre{background:#0d1015;border:1px solid var(--line);border-radius:7px;padding:12px;overflow:auto;max-height:620px;white-space:pre-wrap}.settings{display:grid;grid-template-columns:repeat(3,minmax(180px,1fr));gap:12px}.field label{display:block;color:var(--muted);margin-bottom:5px}.history-item{display:grid;grid-template-columns:80px 1fr 1fr auto;gap:10px;align-items:center;padding:9px;border-bottom:1px solid var(--line)}.badge{font-family:ui-monospace,monospace;color:var(--accent)}
@media(max-width:900px){header{align-items:flex-start;flex-direction:column}.mode-switch{grid-template-columns:1fr}.mode-head{flex-direction:column}.grid{grid-template-columns:1fr}.full{grid-column:auto}.settings{grid-template-columns:1fr}.history-item{grid-template-columns:1fr}.placeholder-grid{grid-template-columns:1fr}.actionbar .status{margin-left:0;width:100%}}
</style>
</head>
<body>
<header>
<div><h1>paperless-local-ai Studio</h1><div class="muted">Zentrale Oberfläche für App-Einstellungen sowie Prompts und Modellparameter der zwei LLM-Stufen. Laufzeit-Einstellungen werden hier verwaltet; die .env enthält nur Docker-Deployment-Werte und den geheimen Paperless-API-Token.</div></div>
<div id="topStatus" class="status">Lade…</div>
</header>
<main>
<nav class="mode-switch" aria-label="LLM-Stufe">
<button type="button" data-mode="classification" class="active"><span class="mode-title">1 · Klassifizierung</span><span class="mode-desc">Läuft zuerst und schreibt Titel, Typ, vorhandenen Korrespondenten, Tags und Datum direkt nach Paperless</span></button>
<button type="button" data-mode="correspondent"><span class="mode-title">2 · Korrespondent-Vorschlag</span><span class="mode-desc">Läuft nur bei leerem Korrespondenten; vorhandene Namen werden gesetzt, neue Namen zur Prüfung vorgeschlagen</span></button>
<button type="button" data-mode="app"><span class="mode-title">App-Einstellungen</span><span class="mode-desc">Paperless/Ollama, Workflow-Tags, OCR und Betriebsverhalten zentral verwalten</span></button>
</nav>

<section id="mode-app" class="mode">
<div class="mode-head"><div><h2>App-Einstellungen</h2><p>Hier liegen alle allgemeinen Laufzeit-Einstellungen der Anwendung. Änderungen werden versioniert gespeichert und von den Workern laufend neu geladen. Nur Docker-Deployment-Werte wie Ports, Volumes, CPU/RAM-Limits und der geheime Paperless-API-Token bleiben bewusst in <code>.env</code>, weil Docker bzw. das Secret bereits vor dem Start der App benötigt werden.</p></div><div id="appConfigStatus" class="config-badge">Lade…</div></div>
<div class="actionbar"><button id="appValidateBtn">Konfiguration prüfen</button><button id="appSaveBtn" class="primary">Änderungen speichern</button><span id="appSaveStatus" class="status">Noch nichts geprüft oder gespeichert.</span></div>
<div class="intro"><strong>Wo stelle ich was ein?</strong> Allgemeine App-Einstellungen stehen ausschließlich hier. Prompt- und Modellparameter bleiben absichtlich in ihrer jeweiligen LLM-Stufe, weil Klassifizierung und Korrespondenten-Fallback unabhängig versioniert und getestet werden. Der Paperless-API-Token wird aus Sicherheitsgründen nicht im Browser angezeigt oder in JSON gespeichert.</div>
<nav class="subtabs" data-mode-tabs="app">
<button type="button" data-subtab="app-connections" class="active">Verbindungen</button><button type="button" data-subtab="app-workflow">Pipeline &amp; Tags</button><button type="button" data-subtab="app-ocr">OCR</button><button type="button" data-subtab="app-runtime">Betrieb</button><button type="button" data-subtab="app-history">Verlauf</button>
</nav>
<section id="app-connections" class="subtab-page active" data-page-mode="app">
<div class="intro"><strong>Verbindungen</strong> Diese URLs werden von allen Komponenten gemeinsam verwendet. Der Paperless-API-Token kommt separat aus der Deployment-Umgebung und wird hier nur als vorhanden/nicht vorhanden angezeigt.</div>
<div class="grid"><div class="panel"><h3>Paperless-ngx</h3><div class="field"><label>Paperless URL</label><input id="appPaperlessUrl" type="text"><div class="field-help">Basis-URL der Paperless-Instanz, z. B. <code>http://paperless:8000</code> oder eine erreichbare LAN-Adresse. Kein abschließender Slash nötig.</div></div><div class="field" style="margin-top:12px"><label>API-Token</label><div id="appTokenStatus" class="status">Lade…</div><div class="field-help">Der Token ist ein Secret und bleibt deshalb bewusst in <code>.env</code> bzw. später einem Docker Secret. Er wird nie über diese Weboberfläche ausgegeben.</div></div></div><div class="panel"><h3>Ollama</h3><div class="field"><label>Ollama URL</label><input id="appOllamaUrl" type="text"><div class="field-help">Basis-URL einer bereits vorhandenen Ollama-Instanz. Ollama wird von paperless-local-ai nicht installiert oder gestartet.</div></div></div><div class="panel full"><div class="row"><button id="appConnectionTestBtn">Verbindungen mit aktuellem Entwurf testen</button><span id="appConnectionStatus" class="status">Noch nicht getestet.</span></div><p class="help">Prüft den momentan sichtbaren Entwurf, ohne ihn zu speichern: Paperless inklusive Token sowie Ollamas <code>/api/tags</code>.</p></div></div>
</section>
<section id="app-workflow" class="subtab-page" data-page-mode="app">
<div class="intro"><strong>Pipeline &amp; Tags</strong> Diese fünf Tags steuern den Übergang zwischen OCR, LLM und menschlicher Prüfung. Wenn du Namen änderst, müssen die entsprechenden Tags in Paperless bereits existieren. OCR-Queue und OCR-Fehler blockieren die LLM-Stufe automatisch; dafür gibt es keine zweite, redundante Einstellung.</div>
<div class="settings"><div class="field"><label>OCR-Queue-Tag</label><input id="appOcrQueueTag"><div class="field-help">Dokumente mit diesem Tag werden vom PaddleOCR-Worker verarbeitet.</div></div><div class="field"><label>OCR-Fehler-Tag</label><input id="appOcrErrorTag"><div class="field-help">Wird gesetzt, wenn die OCR-Verarbeitung fehlschlägt.</div></div><div class="field"><label>LLM-Queue-Tag</label><input id="appLlmQueueTag"><div class="field-help">Nach erfolgreicher OCR wird dieses Tag gesetzt; der Metadata-Worker verarbeitet diese Dokumente.</div></div><div class="field"><label>LLM-Fehler-Tag</label><input id="appLlmErrorTag"><div class="field-help">Wird gesetzt, wenn die LLM-Klassifikation fehlschlägt.</div></div><div class="field"><label>Review-Tag</label><input id="appReviewTag"><div class="field-help">Dokumente bleiben unter diesem Tag zur menschlichen Kontrolle. Persistente Korrespondenten-Vorschläge werden entfernt, sobald das Dokument dieses Review verlässt.</div></div><div class="field"><label>Weitere fachlich auszuschließende Tags</label><input id="appExtraExcludedTags"><div class="field-help">Kommagetrennte zusätzliche Tags, die dem LLM niemals als fachliche Klassifikations-Tags angeboten werden, z. B. <code>TODO</code>. Die fünf technischen Tags oben werden automatisch ausgeschlossen.</div></div></div>
</section>
<section id="app-ocr" class="subtab-page" data-page-mode="app">
<div class="intro"><strong>OCR</strong> Diese Werte gelten für den selektiven PaddleOCR-Lauf. Sie werden vor jedem Poll neu geladen; ein Container-Neustart ist nicht nötig. Das Original-PDF wird weiterhin nicht verändert.</div>
<div class="settings"><div class="field"><label>OCR-Sprache</label><input id="appOcrLanguage"><div class="field-help">PaddleOCR-Sprachcode, z. B. <code>de</code>. Die Sprache bestimmt die verwendeten Erkennungsmodelle.</div></div><div class="field"><label>OCR-Version</label><input id="appOcrVersion"><div class="field-help">PaddleOCR-Modellgeneration. Getesteter Standard: <code>PP-OCRv6</code>.</div></div><div class="field"><label>Gerät</label><input id="appOcrDevice"><div class="field-help">PaddleOCR-Gerät, für den getesteten Low-Power-Betrieb <code>cpu</code>.</div></div></div>
</section>
<section id="app-runtime" class="subtab-page" data-page-mode="app">
<div class="intro"><strong>Betrieb</strong> Zeitintervalle und Sicherheitsmodus der Worker. Docker-Ressourcenlimits stehen bewusst nicht hier, weil sie vom Container-Runtime vor Prozessstart angewendet werden und deshalb Deployment-Einstellungen sind.</div>
<div class="settings"><div class="field"><label>Polling-Intervall in Sekunden</label><input id="appPollInterval" type="number"><div class="field-help">Wie häufig OCR- und Metadata-Worker nach neuen Queue-Dokumenten suchen. Minimum 5 Sekunden.</div></div><div class="field"><label>Review-Cleanup in Sekunden</label><input id="appReviewPruneInterval" type="number"><div class="field-help">Wie häufig alte Review-Records entfernt werden, deren Dokument nicht mehr das Review-Tag trägt. Standard: 3600 = einmal pro Stunde.</div></div><div class="field"><label>Dry-Run</label><select id="appDryRun"><option value="false">Aus – produktiv schreiben</option><option value="true">Ein – keine fachlichen Metadaten schreiben</option></select><div class="field-help">Bei Dry-Run wird die Klassifikation ausgeführt und protokolliert, aber fachliche Paperless-Metadaten und persistente Review-Vorschläge werden nicht geschrieben.</div></div></div>
</section>
<section id="app-history" class="subtab-page" data-page-mode="app">
<div class="intro"><strong>Versionierte App-Einstellungen</strong> Jeder Speichervorgang legt den vorherigen Stand im Verlauf ab. Wiederherstellen erzeugt eine neue aktuelle Version; vorhandene Historie wird nicht gelöscht.</div><div class="panel"><div class="row"><h3>Gespeicherte Versionen</h3><button id="appHistoryRefresh">Verlauf neu laden</button></div><div id="appHistoryList"></div></div>
</section>
</section>

<section id="mode-classification" class="mode active">
<div class="mode-head"><div><h2>Dokumentklassifizierung</h2><p>Stufe 1 läuft für jedes Dokument, das die automatische LLM-Verarbeitung (der Worker) übernimmt. Das Modell bestimmt Titel, Dokumenttyp, einen bereits in Paperless vorhandenen Korrespondenten, fachliche Tags und das Dokumentdatum. Ein gültiges Ergebnis wird direkt in Paperless gespeichert. Bleibt der Korrespondent leer, kann anschließend Stufe 2 übernehmen.</p></div><div id="classConfigStatus" class="config-badge">Lade…</div></div>
<div class="actionbar"><button id="validateBtn">Konfiguration prüfen</button><button id="saveBtn" class="primary">Änderungen speichern</button><span id="saveStatus" class="status">Noch nichts geprüft oder gespeichert.</span></div><div class="intro"><strong>Prüfen oder speichern?</strong> <strong>Konfiguration prüfen</strong> kontrolliert Pflichtfelder, Platzhalter und Werte, speichert aber nichts. <strong>Änderungen speichern</strong> legt eine neue Version an und verwendet sie ab dem nächsten produktiven LLM-Job. Ein Neustart ist nicht nötig.</div>
<nav class="subtabs" data-mode-tabs="classification">
<button type="button" data-subtab="prompt" class="active">Prompt</button><button type="button" data-subtab="preview">Test</button><button type="button" data-subtab="schema">Ausgabe &amp; erlaubte Werte</button><button type="button" data-subtab="settings">Einstellungen</button><button type="button" data-subtab="history">Verlauf</button>
</nav>

<section id="prompt" class="subtab-page active" data-page-mode="classification">
<div class="intro"><strong>Was wird hier bearbeitet?</strong> Der System-Prompt enthält die allgemeinen Regeln für Stufe 1. Der Klassifizierungs-Prompt enthält den konkreten Arbeitsauftrag für ein Dokument. Platzhalter wie <code>{{DOCUMENT_TEXT}}</code> werden erst unmittelbar vor dem Modellaufruf mit den Daten des jeweiligen Paperless-Dokuments ersetzt.</div>
<div class="grid">
<div class="panel"><h3>System-Prompt</h3><p class="help">Gilt bei jedem Klassifizierungs-Lauf und legt Rolle, Sicherheitsregeln und allgemeine Ausgabevorgaben fest. Dokumentbezogene Inhalte gehören in den Klassifizierungs-Prompt; <code>{{DOCUMENT_TEXT}}</code> muss dort enthalten bleiben.</p><textarea id="systemPrompt"></textarea></div>
<div class="panel"><h3>Klassifizierungs-Prompt</h3><p class="help">Konkrete Anweisung für ein einzelnes Dokument. Hier legst du fest, wie Titel, Dokumenttyp, vorhandener Korrespondent, Tags und Datum bestimmt werden. Die gerenderte Fassung wird als User-Nachricht an Ollama gesendet.</p><textarea id="classificationTemplate"></textarea></div>
<div class="panel full"><h3>Verfügbare Platzhalter</h3><p class="help">Beim Ausführen ersetzt das Studio jeden Platzhalter durch den aktuellen Wert des Test- bzw. Produktivdokuments. Varianten mit <code>_JSON</code> liefern eine korrekt formatierte JSON-Liste; <code>_LINES</code> liefert dieselben Werte lesbar mit einem Eintrag pro Zeile. <code>{{DOCUMENT_TEXT}}</code> ist Pflicht und darf nicht entfernt werden.</p><div id="placeholders" class="placeholder-grid"></div></div>
</div>
</section>

<section id="preview" class="subtab-page" data-page-mode="classification">
<div class="intro"><strong>Was passiert beim Test?</strong> Du wählst ein vorhandenes Paperless-Dokument über seine ID. <strong>Finalen Prompt anzeigen</strong> lädt Dokument und Taxonomie und zeigt exakt, was an das Modell gesendet würde – ohne Modellaufruf. <strong>Mit Modell testen</strong> führt zusätzlich einen echten Ollama-Aufruf aus. Beide Varianten verwenden den aktuell sichtbaren, auch noch nicht gespeicherten Entwurf und ändern niemals das Paperless-Dokument.</div>
<div class="grid">
<div class="panel full"><div class="row"><div><label>Paperless-Dokument-ID</label><input id="docId" type="number" min="1" value="93"><div class="field-help">Numerische Dokument-ID aus Paperless, z. B. aus der Dokument-URL oder API.</div></div><button id="previewBtn">Finalen Prompt anzeigen</button><button id="testBtn" class="primary">Mit Modell testen</button></div><p class="help">Ein echter Modelltest verwendet dieselbe gemeinsame KI-Sperre (AI-Lock) wie OCR und die produktiven LLM-Jobs. Dadurch laufen diese rechenintensiven Aufgaben nicht gleichzeitig; ist der KI-Slot belegt, wartet der Test.</p><div id="testStatus" class="status">Bereit für Vorschau oder Modelltest.</div></div>
<div class="panel"><h3>System-Nachricht an das Modell</h3><p class="help">Exakt gerenderter System-Prompt dieses Tests.</p><pre id="systemPreview"></pre></div>
<div class="panel"><h3>User-Nachricht an das Modell</h3><p class="help">Exakt gerenderter Klassifizierungs-Prompt inklusive eingesetzter Platzhalter.</p><pre id="userPreview"></pre></div>
<div class="panel"><h3>Modellantwort und Validierung</h3><p class="help">Wird nur bei <strong>Mit Modell testen</strong> gefüllt. Zeigt den strukturierten Vorschlag, Validierungsfehler und Laufzeitdaten.</p><pre id="testResult"></pre></div>
<div class="panel"><h3>Verwendete Testdaten</h3><p class="help">Technische Angaben zum gerenderten Request, z. B. Konfigurationsversion und verwendete Textmenge.</p><pre id="previewMeta"></pre></div>
</div>
</section>

<section id="schema" class="subtab-page" data-page-mode="classification">
<div class="intro"><strong>Was ist hier zu sehen?</strong> Das Ausgabe-Schema ist der feste JSON-Vertrag, den die Modellantwort erfüllen muss. Die erlaubten Paperless-Werte zeigen die Taxonomie, die bei der letzten Vorschau oder beim letzten Modelltest geladen wurde. Für Dokumenttyp, Korrespondent und Tags kann Stufe 1 nur Werte aus diesen aktuellen Listen verwenden.</div>
<div class="grid"><div class="panel"><h3>Erwartetes JSON-Ausgabeformat</h3><p class="help">Legt Felder, Datentypen und erlaubte Werte der Modellantwort fest. Es wird automatisch aus der aktuellen Konfiguration erzeugt.</p><pre id="schemaPreview"></pre></div><div class="panel"><h3>Aktuell erlaubte Paperless-Werte</h3><p class="help">Bei der letzten Vorschau bzw. beim letzten Modelltest aus Paperless geladene Dokumenttypen, Korrespondenten und fachliche Tags. Technische Prozess-Tags wie <code>Inbox</code> oder <code>LLM</code> sind ausgeschlossen.</p><pre id="taxonomyPreview"></pre></div></div>
</section>

<section id="settings" class="subtab-page" data-page-mode="classification">
<div class="intro"><strong>Diese Einstellungen gelten nur für Stufe 1.</strong> Änderungen werden erst nach <strong>Änderungen speichern</strong> produktiv. Sie verändern weder die Ollama-App noch das installierte Modell selbst.</div>
<div class="panel"><div class="settings">
<div class="field"><label>Ollama-Modell <span class="muted">(model)</span></label><input id="model"><div class="field-help">Exakter Name eines bereits in Ollama installierten Modells, z. B. <code>qwen3.5:4b</code>. Das Studio lädt oder installiert keine Modelle.</div></div>
<div class="field"><label>Kontextfenster in Tokens <span class="muted">(num_ctx)</span></label><input id="numCtx" type="number"><div class="field-help">Maximaler Kontext, den Ollama für Prompt und Antwort bereitstellt. Ein größerer Wert erlaubt mehr Text, benötigt aber mehr Speicher und kann langsamer sein.</div></div>
<div class="field"><label>Maximale Antwortlänge in Tokens <span class="muted">(num_predict)</span></label><input id="numPredict" type="number"><div class="field-help">Obergrenze für die vom Modell erzeugte JSON-Antwort. Zu klein kann die Antwort abschneiden; der Wert beeinflusst nicht die Länge des eingelesenen Dokumenttexts.</div></div>
<div class="field"><label>Zufälligkeit der Ausgabe <span class="muted">(temperature)</span></label><input id="temperature" type="number" min="0" max="2" step="0.05"><div class="field-help"><code>0</code> liefert möglichst reproduzierbare Ergebnisse und ist für Metadaten empfohlen. Höhere Werte machen Antworten variabler.</div></div>
<div class="field"><label>Zusätzliches Modell-Reasoning <span class="muted">(think)</span></label><select id="think"><option value="false">Aus</option><option value="true">Ein</option></select><div class="field-help"><strong>Aus</strong> ist für diese kurze strukturierte Klassifikation vorgesehen. <strong>Ein</strong> aktiviert den Thinking-Modus des Modells und kostet zusätzliche Zeit bzw. Tokens.</div></div>
<div class="field"><label>Modell nach dem Job geladen halten <span class="muted">(keep_alive)</span></label><input id="keepAlive"><div class="field-help">Wird direkt an Ollama übergeben. <code>0</code> entlädt das Modell nach dem Request; z. B. <code>5m</code> hält es fünf Minuten geladen. Längeres Keep-Alive belegt entsprechend länger RAM.</div></div>
<div class="field"><label>Maximal verwendeter Dokumenttext in Zeichen <span class="muted">(content_char_limit)</span></label><input id="contentLimit" type="number"><div class="field-help">So viele Zeichen aus Paperless-<code>content</code> dürfen höchstens in den Prompt. Kürzere Dokumente werden vollständig verwendet; längere werden nach der Einstellung darunter gekürzt.</div></div>
<div class="field"><label>Anteil vom Dokumentanfang bei Kürzung <span class="muted">(content_head_ratio)</span></label><input id="headRatio" type="number" min="0.5" max="0.95" step="0.05"><div class="field-help">Wirkt nur, wenn der Dokumenttext das Zeichenlimit überschreitet. <code>0.75</code> bedeutet: 75 % des behaltenen Textes kommen vom Anfang, 25 % vom Ende.</div></div>
<div class="field"><label>Maximal erlaubte fachliche Tags <span class="muted">(max_tags)</span></label><input id="maxTags" type="number" min="1" max="10"><div class="field-help">Begrenzt, wie viele fachliche Tags die Modellantwort enthalten darf. Der Wert wird direkt in Ausgabe-Schema und Validierung übernommen; Prozess-Tags zählen nicht dazu.</div></div>
<div class="field"><label>Maximale Wartezeit auf Ollama in Sekunden <span class="muted">(timeout)</span></label><input id="ollamaTimeout" type="number"><div class="field-help">So lange wartet der Worker höchstens auf den Modellaufruf. Wird die Zeit überschritten, gilt der Request als fehlgeschlagen und läuft in die normale Fehlerbehandlung.</div></div>
</div></div>
</section>

<section id="history" class="subtab-page" data-page-mode="classification">
<div class="intro"><strong>Was wird versioniert?</strong> Bei jedem Speichern werden Prompt und Einstellungen gemeinsam als neue Klassifizierungs-Version gespeichert. Eine Wiederherstellung überschreibt die Historie nicht: Der ausgewählte alte Stand wird als neue aktive Version angelegt.</div>
<div class="panel"><div class="row"><h3>Gespeicherte Versionen</h3><button id="historyRefresh">Verlauf neu laden</button></div><p class="help">Mit <strong>Diese Version wiederherstellen</strong> wird der ausgewählte Stand erneut als aktuelle Konfiguration gespeichert. Die momentan aktive Fassung bleibt als eigene Version erhalten.</p><div id="historyList"></div></div>
</section>
</section>

<section id="mode-correspondent" class="mode">
<div class="mode-head"><div><h2>Korrespondent-Vorschlag</h2><p>Stufe 2 ist ein optionaler Fallback und läuft nur, wenn Stufe 1 keinen Korrespondenten gefunden hat und <strong>Produktiv verwenden</strong> eingeschaltet ist. Sie ermittelt ausschließlich den Absender oder Aussteller. Ein eindeutig bereits vorhandener Paperless-Korrespondent wird automatisch gesetzt. Ein wirklich neuer Name wird niemals automatisch angelegt, sondern erscheint als native Paperless-Suggestion zur Bestätigung. Ist kein sicherer Name erkennbar, passiert nichts.</p></div><div id="corrConfigStatus" class="config-badge">Lade…</div></div>
<div class="actionbar"><button id="corrValidateBtn">Konfiguration prüfen</button><button id="corrSaveBtn" class="primary">Änderungen speichern</button><span id="corrSaveStatus" class="status">Noch nichts geprüft oder gespeichert.</span></div><div class="intro"><strong>Prüfen oder speichern?</strong> <strong>Konfiguration prüfen</strong> kontrolliert Pflichtfelder, Platzhalter und Werte, speichert aber nichts. <strong>Änderungen speichern</strong> legt eine neue Version an. Ob Stufe 2 danach produktiv ausgeführt wird, bestimmt der Schalter <strong>Produktiv verwenden</strong> unter Einstellungen.</div>
<nav class="subtabs" data-mode-tabs="correspondent">
<button type="button" data-subtab="corr-prompt" class="active">Prompt</button><button type="button" data-subtab="corr-test">Test</button><button type="button" data-subtab="corr-settings">Einstellungen</button><button type="button" data-subtab="corr-history">Verlauf</button>
</nav>

<section id="corr-prompt" class="subtab-page active" data-page-mode="correspondent">
<div class="intro"><strong>Was wird hier bearbeitet?</strong> Diese beiden Prompts gehören ausschließlich zu Stufe 2. Sie beeinflussen weder Titel, Dokumenttyp, Tags noch Datum aus Stufe 1. Anders als Stufe 1 darf dieser Lauf auch einen neuen Korrespondentennamen vorschlagen; angelegt wird er dadurch noch nicht.</div>
<div class="grid">
<div class="panel"><h3>System-Prompt</h3><p class="help">Allgemeine Rolle und Sicherheitsregeln für die Absender-Erkennung. Der eigentliche Dokumenttext gehört in den Korrespondenten-Prompt.</p><textarea id="corrSystemPrompt"></textarea></div>
<div class="panel"><h3>Korrespondenten-Prompt</h3><p class="help">Konkreter Arbeitsauftrag für ein Dokument. Die Modellantwort enthält ausschließlich <code>correspondent</code>: entweder einen vorhandenen oder neuen sinnvollen Absendernamen oder einen leeren String, wenn der Absender nicht zuverlässig bestimmbar ist.</p><textarea id="corrPromptTemplate"></textarea></div>
<div class="panel full"><h3>Verfügbare Platzhalter</h3><p class="help"><code>{{DOCUMENT_TEXT}}</code> ist Pflicht. <code>{{CORRESPONDENTS_JSON}}</code> bzw. <code>{{CORRESPONDENTS_LINES}}</code> liefern die bereits vorhandenen Paperless-Korrespondenten als Referenz. Diese Liste ist in Stufe 2 keine harte Einschränkung: Wenn der tatsächliche Absender noch nicht existiert, darf das Modell einen neuen Namen vorschlagen.</p><div id="corrPlaceholders" class="placeholder-grid"></div></div>
</div>
</section>

<section id="corr-test" class="subtab-page" data-page-mode="correspondent">
<div class="intro"><strong>Was passiert beim Test?</strong> <strong>Finalen Prompt anzeigen</strong> zeigt für ein echtes Paperless-Dokument exakt die Eingabe von Stufe 2, ohne das Modell aufzurufen. <strong>Mit Modell testen</strong> führt einen echten Ollama-Aufruf aus. Es werden weder Paperless-Metadaten noch persistente Review-Suggestions geschrieben. Der Test funktioniert auch dann, wenn <strong>Produktiv verwenden</strong> ausgeschaltet ist.</div>
<div class="grid">
<div class="panel full"><div class="row"><div><label>Paperless-Dokument-ID</label><input id="corrDocId" type="number" min="1" value="93"><div class="field-help">Numerische Dokument-ID aus Paperless, z. B. aus der Dokument-URL oder API.</div></div><button id="corrPreviewBtn">Finalen Prompt anzeigen</button><button id="corrTestBtn" class="primary">Mit Modell testen</button></div><p class="help">Vorschau und Modelltest verwenden den aktuell sichtbaren, auch noch nicht gespeicherten Entwurf. Ein echter Modelltest verwendet die gemeinsame KI-Sperre (AI-Lock), damit OCR und LLM-Jobs nicht gleichzeitig die verfügbaren Ressourcen belegen.</p><div id="corrTestStatus" class="status">Bereit für Vorschau oder Modelltest.</div></div>
<div class="panel"><h3>System-Nachricht an das Modell</h3><p class="help">Exakt gerenderter System-Prompt dieses Tests.</p><pre id="corrSystemPreview"></pre></div>
<div class="panel"><h3>User-Nachricht an das Modell</h3><p class="help">Exakt gerenderter Korrespondenten-Prompt inklusive eingesetzter Platzhalter.</p><pre id="corrUserPreview"></pre></div>
<div class="panel"><h3>Erwartetes JSON-Ausgabeformat</h3><p class="help">Stufe 2 darf nur das Feld <code>correspondent</code> zurückgeben.</p><pre id="corrSchemaPreview"></pre></div>
<div class="panel"><h3>Modellantwort und Validierung</h3><p class="help">Wird nur bei <strong>Mit Modell testen</strong> gefüllt. Zeigt Kandidat, Validierungsfehler und Laufzeitdaten.</p><pre id="corrTestResult"></pre></div>
<div class="panel full"><h3>Verwendete Testdaten</h3><p class="help">Technische Angaben zum gerenderten Request, z. B. Konfigurationsversion und verwendete Textmenge.</p><pre id="corrPreviewMeta"></pre></div>
</div>
</section>

<section id="corr-settings" class="subtab-page" data-page-mode="correspondent">
<div class="intro"><strong>Diese Einstellungen gelten nur für Stufe 2.</strong> Hier bestimmst du sowohl, ob der Fallback im produktiven Worker automatisch ausgeführt wird, als auch welche Modell- und Textparameter er dafür verwendet. Tests im Test-Tab sind unabhängig vom Aktiv-Schalter immer möglich.</div>
<div class="grid">
<div class="panel full"><h3>Produktiver Einsatz</h3><div class="settings"><div class="field"><label>Produktiv verwenden <span class="muted">(enabled)</span></label><select id="corrEnabled"><option value="false">Aus – nur manuell testen</option><option value="true">Ein – bei leerem Korrespondenten ausführen</option></select><div class="field-help">Bei <strong>Ein</strong> startet Stufe 2 automatisch nur dann, wenn Stufe 1 keinen Korrespondenten geliefert hat. Ein exakt vorhandener Paperless-Name wird direkt gesetzt; ein neuer Name wird nur als Suggestion zur Bestätigung gespeichert. Bei leerem oder unsicherem Ergebnis wird nichts geändert. Der Schalter beeinflusst manuelle Tests nicht.</div></div></div></div>
<div class="panel full"><h3>Modell- und Request-Parameter</h3><div class="settings">
<div class="field"><label>Ollama-Modell <span class="muted">(model)</span></label><input id="corrModel"><div class="field-help">Exakter Name eines bereits in Ollama installierten Modells. Das Studio lädt oder installiert keine Modelle.</div></div>
<div class="field"><label>Kontextfenster in Tokens <span class="muted">(num_ctx)</span></label><input id="corrNumCtx" type="number"><div class="field-help">Maximaler Kontext für Prompt und Antwort dieses zweiten Modelllaufs. Größere Werte benötigen mehr Speicher und können langsamer sein.</div></div>
<div class="field"><label>Maximale Antwortlänge in Tokens <span class="muted">(num_predict)</span></label><input id="corrNumPredict" type="number"><div class="field-help">Obergrenze für die kurze JSON-Antwort. Da nur ein Name oder ein leerer String erwartet wird, ist hier normalerweise ein deutlich kleinerer Wert als bei Stufe 1 ausreichend.</div></div>
<div class="field"><label>Zufälligkeit der Ausgabe <span class="muted">(temperature)</span></label><input id="corrTemperature" type="number" min="0" max="2" step="0.05"><div class="field-help"><code>0</code> ist für reproduzierbare Absendernamen empfohlen. Höhere Werte machen Vorschläge variabler und erhöhen das Risiko unnötiger Namensvarianten.</div></div>
<div class="field"><label>Zusätzliches Modell-Reasoning <span class="muted">(think)</span></label><select id="corrThink"><option value="false">Aus</option><option value="true">Ein</option></select><div class="field-help"><strong>Aus</strong> ist für die kurze Absender-Erkennung vorgesehen. <strong>Ein</strong> aktiviert den Thinking-Modus des Modells und kostet zusätzliche Zeit bzw. Tokens.</div></div>
<div class="field"><label>Modell nach dem Job geladen halten <span class="muted">(keep_alive)</span></label><input id="corrKeepAlive"><div class="field-help">Wird direkt an Ollama übergeben. <code>0</code> entlädt das Modell nach dem Request; z. B. <code>5m</code> hält es fünf Minuten geladen.</div></div>
<div class="field"><label>Maximal verwendeter Dokumenttext in Zeichen <span class="muted">(content_char_limit)</span></label><input id="corrContentLimit" type="number"><div class="field-help">So viele Zeichen aus Paperless-<code>content</code> dürfen höchstens in den Korrespondenten-Prompt. Kürzere Dokumente werden vollständig verwendet.</div></div>
<div class="field"><label>Anteil vom Dokumentanfang bei Kürzung <span class="muted">(content_head_ratio)</span></label><input id="corrHeadRatio" type="number" min="0.5" max="0.95" step="0.05"><div class="field-help">Wirkt nur bei gekürzten Dokumenten. <code>0.75</code> bedeutet: 75 % des behaltenen Textes kommen vom Anfang, 25 % vom Ende.</div></div>
<div class="field"><label>Maximale Wartezeit auf Ollama in Sekunden <span class="muted">(timeout)</span></label><input id="corrTimeout" type="number"><div class="field-help">So lange wartet der Worker höchstens auf den zweiten Modelllauf. Wird die Zeit überschritten, gilt dieser Aufruf als fehlgeschlagen.</div></div>
</div></div>
</div>
</section>

<section id="corr-history" class="subtab-page" data-page-mode="correspondent">
<div class="intro"><strong>Was wird versioniert?</strong> Prompt, Aktiv-Schalter und Einstellungen von Stufe 2 werden gemeinsam versioniert – vollständig getrennt von Stufe 1. Beim Wiederherstellen wird der ausgewählte alte Stand als neue aktuelle Version gespeichert; bestehende Historie geht nicht verloren.</div>
<div class="panel"><div class="row"><h3>Gespeicherte Versionen</h3><button id="corrHistoryRefresh">Verlauf neu laden</button></div><p class="help">Mit <strong>Diese Version wiederherstellen</strong> wird der ausgewählte Stand erneut als aktuelle Korrespondenten-Konfiguration gespeichert. Die momentan aktive Fassung bleibt als eigene Version erhalten.</p><div id="corrHistoryList"></div></div>
</section>
</section>
</main>
<script>
let currentConfig=null;
const $=id=>document.getElementById(id);
function draft(){return {version:currentConfig?.version||1,updated_at:currentConfig?.updated_at||null,system_prompt:$('systemPrompt').value,classification_template:$('classificationTemplate').value,model:$('model').value.trim(),num_ctx:Number($('numCtx').value),num_predict:Number($('numPredict').value),temperature:Number($('temperature').value),think:$('think').value==='true',keep_alive:/^-?\d+(\.\d+)?$/.test($('keepAlive').value.trim())?Number($('keepAlive').value):$('keepAlive').value,content_char_limit:Number($('contentLimit').value),content_head_ratio:Number($('headRatio').value),max_tags:Number($('maxTags').value),ollama_timeout_seconds:Number($('ollamaTimeout').value)}}
function fill(c){currentConfig=c;$('systemPrompt').value=c.system_prompt;$('classificationTemplate').value=c.classification_template;$('model').value=c.model;$('numCtx').value=c.num_ctx;$('numPredict').value=c.num_predict;$('temperature').value=c.temperature;$('think').value=String(c.think);$('keepAlive').value=c.keep_alive;$('contentLimit').value=c.content_char_limit;$('headRatio').value=c.content_head_ratio;$('maxTags').value=c.max_tags;$('ollamaTimeout').value=c.ollama_timeout_seconds;$('classConfigStatus').textContent=`Aktive Konfiguration · v${c.version} · ${c.model}`}
async function api(path,opts={}){const r=await fetch(path,{headers:{'Content-Type':'application/json'},...opts});const t=await r.text();let data;try{data=JSON.parse(t)}catch{data={error:t}}if(!r.ok)throw new Error(data.error||`${r.status} ${r.statusText}`);return data}
async function init(){try{const s=await api('/api/state');fill(s.config);$('placeholders').innerHTML=Object.entries(s.placeholders).map(([k,v])=>`<div class="placeholder-item"><code>{{${k}}}</code><span>${v}</span></div>`).join('');await loadHistory();$('topStatus').textContent='Prompt Studio bereit';$('topStatus').className='status ok'}catch(e){$('topStatus').textContent=e.message;$('topStatus').className='status bad'}}
function setStatus(id,msg,ok=true){$(id).textContent=msg;$(id).className='status '+(ok?'ok':'bad')}
$('validateBtn').onclick=async()=>{try{const r=await api('/api/config/validate',{method:'POST',body:JSON.stringify({config:draft()})});setStatus('saveStatus',`Konfiguration gültig · noch nicht gespeichert · SHA ${r.config_sha256.slice(0,12)}`)}catch(e){setStatus('saveStatus',e.message,false)}};
$('saveBtn').onclick=async()=>{try{const r=await api('/api/config/save',{method:'POST',body:JSON.stringify({config:draft()})});fill(r.config);setStatus('saveStatus',`Gespeichert und ab dem nächsten Klassifizierungs-Job aktiv · v${r.config.version}`);await loadHistory()}catch(e){setStatus('saveStatus',e.message,false)}};
async function doPreview(run){const id=Number($('docId').value);if(!id)return;setStatus('testStatus',run?'Modelltest läuft…':'Finaler Prompt wird vorbereitet…');try{const r=await api(run?'/api/test':'/api/preview',{method:'POST',body:JSON.stringify({document_id:id,config:draft()})});$('systemPreview').textContent=r.rendered.system_prompt;$('userPreview').textContent=r.rendered.user_prompt;$('schemaPreview').textContent=JSON.stringify(r.rendered.schema,null,2);$('taxonomyPreview').textContent=JSON.stringify(r.taxonomy,null,2);$('previewMeta').textContent=JSON.stringify(r.meta,null,2);$('testResult').textContent=run?JSON.stringify({suggestion:r.suggestion,validation_errors:r.validation_errors,performance:r.performance},null,2):'';setStatus('testStatus',run?'Modelltest abgeschlossen · Paperless wurde nicht verändert.':'Finaler Prompt angezeigt · das Modell wurde nicht aufgerufen.')}catch(e){setStatus('testStatus',e.message,false)}}
$('previewBtn').onclick=()=>doPreview(false);$('testBtn').onclick=()=>doPreview(true);

let currentAppConfig=null;
function appDraft(){return {version:currentAppConfig?.version||1,updated_at:currentAppConfig?.updated_at||null,connections:{paperless_url:$('appPaperlessUrl').value.trim(),ollama_url:$('appOllamaUrl').value.trim()},workflow:{ocr_queue_tag:$('appOcrQueueTag').value.trim(),ocr_error_tag:$('appOcrErrorTag').value.trim(),llm_queue_tag:$('appLlmQueueTag').value.trim(),llm_error_tag:$('appLlmErrorTag').value.trim(),review_tag:$('appReviewTag').value.trim(),extra_excluded_tags:$('appExtraExcludedTags').value.split(',').map(x=>x.trim()).filter(Boolean)},ocr:{language:$('appOcrLanguage').value.trim(),version:$('appOcrVersion').value.trim(),device:$('appOcrDevice').value.trim()},runtime:{poll_interval_seconds:Number($('appPollInterval').value),review_prune_interval_seconds:Number($('appReviewPruneInterval').value),dry_run:$('appDryRun').value==='true'}}}
function appFill(c,tokenConfigured){currentAppConfig=c;$('appPaperlessUrl').value=c.connections.paperless_url;$('appOllamaUrl').value=c.connections.ollama_url;$('appOcrQueueTag').value=c.workflow.ocr_queue_tag;$('appOcrErrorTag').value=c.workflow.ocr_error_tag;$('appLlmQueueTag').value=c.workflow.llm_queue_tag;$('appLlmErrorTag').value=c.workflow.llm_error_tag;$('appReviewTag').value=c.workflow.review_tag;$('appExtraExcludedTags').value=(c.workflow.extra_excluded_tags||[]).join(', ');$('appOcrLanguage').value=c.ocr.language;$('appOcrVersion').value=c.ocr.version;$('appOcrDevice').value=c.ocr.device;$('appPollInterval').value=c.runtime.poll_interval_seconds;$('appReviewPruneInterval').value=c.runtime.review_prune_interval_seconds;$('appDryRun').value=String(c.runtime.dry_run);$('appConfigStatus').textContent=`v${c.version} · ${c.runtime.dry_run?'DRY-RUN':'PRODUKTIV'}`;$('appConfigStatus').style.color=c.runtime.dry_run?'var(--warn)':'var(--ok)';$('appTokenStatus').textContent=tokenConfigured?'API-Token ist in der Deployment-Umgebung gesetzt.':'API-Token fehlt in der Deployment-Umgebung.';$('appTokenStatus').className='status '+(tokenConfigured?'ok':'bad')}
function renderAppHistory(items){$('appHistoryList').innerHTML=items.length?items.map(x=>`<div class="history-item"><span class="badge">v${x.version??'?'}</span><span>${x.file}</span><span class="muted">${x.updated_at||''}<br>${(x.config_sha256||'').slice(0,16)}</span><button onclick="restoreAppHistory('${x.file}')">Diese Version wiederherstellen</button></div>`).join(''):'<p class="muted">Noch keine ältere gespeicherte Version vorhanden.</p>'}
async function loadApp(){try{const r=await api('/api/app/state');appFill(r.config,r.token_configured);renderAppHistory(r.history||[])}catch(e){$('appConfigStatus').textContent='Fehler';$('appConfigStatus').style.color='var(--bad)';setStatus('appSaveStatus',e.message,false)}}
$('appValidateBtn').onclick=async()=>{try{const r=await api('/api/app/validate',{method:'POST',body:JSON.stringify({config:appDraft()})});setStatus('appSaveStatus',`Konfiguration gültig · noch nicht gespeichert · SHA ${r.config_sha256.slice(0,12)}`)}catch(e){setStatus('appSaveStatus',e.message,false)}};
$('appSaveBtn').onclick=async()=>{try{const r=await api('/api/app/save',{method:'POST',body:JSON.stringify({config:appDraft()})});appFill(r.config,r.token_configured);setStatus('appSaveStatus',`Gespeichert · AppConfig v${r.config.version}. Worker laden die Laufzeit-Einstellungen automatisch neu.`);renderAppHistory(r.history||[])}catch(e){setStatus('appSaveStatus',e.message,false)}};
$('appConnectionTestBtn').onclick=async()=>{setStatus('appConnectionStatus','Verbindungen werden geprüft…');try{const r=await api('/api/app/connections/test',{method:'POST',body:JSON.stringify({config:appDraft()})});setStatus('appConnectionStatus',`Paperless: ${r.paperless.ok?'OK':'FEHLER'}${r.paperless.detail?' · '+r.paperless.detail:''}\nOllama: ${r.ollama.ok?'OK':'FEHLER'}${r.ollama.detail?' · '+r.ollama.detail:''}`,r.paperless.ok&&r.ollama.ok)}catch(e){setStatus('appConnectionStatus',e.message,false)}};
async function refreshAppHistory(){const r=await api('/api/app/history');renderAppHistory(r.items||[])}
$('appHistoryRefresh').onclick=()=>refreshAppHistory().catch(e=>setStatus('appSaveStatus',e.message,false));
window.restoreAppHistory=async file=>{if(!confirm(`Diese App-Einstellungen wiederherstellen? Der ausgewählte Stand wird als neue aktuelle Version gespeichert; die jetzige Fassung bleibt im Verlauf erhalten.\n\nDatei: ${file}`))return;try{const r=await api('/api/app/history/restore',{method:'POST',body:JSON.stringify({file})});appFill(r.config,r.token_configured);renderAppHistory(r.history||[]);setStatus('appSaveStatus',`Wiederhergestellt und als neue aktuelle Version gespeichert · v${r.config.version}`)}catch(e){alert(e.message)}};

let currentCorrConfig=null;
function corrDraft(){return {version:currentCorrConfig?.version||1,updated_at:currentCorrConfig?.updated_at||null,enabled:$('corrEnabled').value==='true',system_prompt:$('corrSystemPrompt').value,prompt_template:$('corrPromptTemplate').value,model:$('corrModel').value.trim(),num_ctx:Number($('corrNumCtx').value),num_predict:Number($('corrNumPredict').value),temperature:Number($('corrTemperature').value),think:$('corrThink').value==='true',keep_alive:/^-?\d+(\.\d+)?$/.test($('corrKeepAlive').value.trim())?Number($('corrKeepAlive').value):$('corrKeepAlive').value,content_char_limit:Number($('corrContentLimit').value),content_head_ratio:Number($('corrHeadRatio').value),ollama_timeout_seconds:Number($('corrTimeout').value)}}
function corrFill(c){currentCorrConfig=c;$('corrEnabled').value=String(c.enabled);$('corrSystemPrompt').value=c.system_prompt;$('corrPromptTemplate').value=c.prompt_template;$('corrModel').value=c.model;$('corrNumCtx').value=c.num_ctx;$('corrNumPredict').value=c.num_predict;$('corrTemperature').value=c.temperature;$('corrThink').value=String(c.think);$('corrKeepAlive').value=c.keep_alive;$('corrContentLimit').value=c.content_char_limit;$('corrHeadRatio').value=c.content_head_ratio;$('corrTimeout').value=c.ollama_timeout_seconds;$('corrConfigStatus').textContent=`${c.enabled?'PRODUKTIV EIN':'PRODUKTIV AUS'} · v${c.version} · ${c.model}`;$('corrConfigStatus').style.color=c.enabled?'var(--ok)':'var(--muted)'}
function renderCorrHistory(items){$('corrHistoryList').innerHTML=items.length?items.map(x=>`<div class="history-item"><span class="badge">v${x.version??'?'}</span><span>${x.file}</span><span class="muted">${x.updated_at||''}<br>${(x.config_sha256||'').slice(0,16)}</span><button onclick="restoreCorrHistory('${x.file}')">Diese Version wiederherstellen</button></div>`).join(''):'<p class="muted">Noch keine ältere gespeicherte Version vorhanden.</p>'}
async function loadCorrespondent(){try{const s=await api('/api/correspondent/state');corrFill(s.config);$('corrPlaceholders').innerHTML=Object.entries(s.placeholders).map(([k,v])=>`<div class="placeholder-item"><code>{{${k}}}</code><span>${v}</span></div>`).join('');renderCorrHistory(s.history||[])}catch(e){$('corrConfigStatus').textContent='Fehler';$('corrConfigStatus').style.color='var(--bad)';setStatus('corrSaveStatus',e.message,false)}}
async function refreshCorrHistory(){const s=await api('/api/correspondent/state');renderCorrHistory(s.history||[])}
$('corrValidateBtn').onclick=async()=>{try{const r=await api('/api/correspondent/validate',{method:'POST',body:JSON.stringify({config:corrDraft()})});setStatus('corrSaveStatus',`Konfiguration gültig · noch nicht gespeichert · SHA ${r.config_sha256.slice(0,12)}`)}catch(e){setStatus('corrSaveStatus',e.message,false)}};
$('corrSaveBtn').onclick=async()=>{try{const r=await api('/api/correspondent/save',{method:'POST',body:JSON.stringify({config:corrDraft()})});corrFill(r.config);setStatus('corrSaveStatus',`Gespeichert als v${r.config.version} · produktiver Fallback ${r.config.enabled?'EIN':'AUS'}`);await refreshCorrHistory()}catch(e){setStatus('corrSaveStatus',e.message,false)}};
async function corrPreview(run){const id=Number($('corrDocId').value);if(!id)return;setStatus('corrTestStatus',run?'Modelltest läuft…':'Finaler Prompt wird vorbereitet…');try{const r=await api(run?'/api/correspondent/test':'/api/correspondent/preview',{method:'POST',body:JSON.stringify({document_id:id,config:corrDraft()})});$('corrSystemPreview').textContent=r.rendered.system_prompt;$('corrUserPreview').textContent=r.rendered.user_prompt;$('corrSchemaPreview').textContent=JSON.stringify(r.rendered.schema,null,2);$('corrPreviewMeta').textContent=JSON.stringify(r.meta,null,2);$('corrTestResult').textContent=run?JSON.stringify({suggestion:r.suggestion,validation_errors:r.validation_errors,performance:r.performance},null,2):'';setStatus('corrTestStatus',run?'Modelltest abgeschlossen · Paperless wurde nicht verändert und kein Korrespondenten-Vorschlag gespeichert.':'Finaler Prompt angezeigt · das Modell wurde nicht aufgerufen.')}catch(e){setStatus('corrTestStatus',e.message,false)}}
$('corrPreviewBtn').onclick=()=>corrPreview(false);$('corrTestBtn').onclick=()=>corrPreview(true);$('corrHistoryRefresh').onclick=()=>refreshCorrHistory().catch(e=>setStatus('corrSaveStatus',e.message,false));
window.restoreCorrHistory=async file=>{if(!confirm(`Diese Korrespondenten-Version wiederherstellen? Der ausgewählte Stand wird als neue aktuelle Version gespeichert; die jetzige Fassung bleibt im Verlauf erhalten.\n\nDatei: ${file}`))return;try{const r=await api('/api/correspondent/history/restore',{method:'POST',body:JSON.stringify({file})});corrFill(r.config);setStatus('corrSaveStatus',`Wiederhergestellt und als neue aktuelle Version gespeichert · v${r.config.version}`);await refreshCorrHistory()}catch(e){alert(e.message)}};

async function loadHistory(){try{const r=await api('/api/history');$('historyList').innerHTML=r.items.length?r.items.map(x=>`<div class="history-item"><span class="badge">v${x.version??'?'}</span><span>${x.file}</span><span class="muted">${x.updated_at||''}<br>${(x.config_sha256||'').slice(0,16)}</span><button onclick="restoreHistory('${x.file}')">Diese Version wiederherstellen</button></div>`).join(''):'<p class="muted">Noch keine ältere gespeicherte Version vorhanden.</p>'}catch(e){$('historyList').textContent=e.message}}
window.restoreHistory=async file=>{if(!confirm(`Diese Klassifizierungs-Version wiederherstellen? Der ausgewählte Stand wird als neue aktuelle Version gespeichert; die jetzige Fassung bleibt im Verlauf erhalten.\n\nDatei: ${file}`))return;try{const r=await api('/api/history/restore',{method:'POST',body:JSON.stringify({file})});fill(r.config);setStatus('saveStatus',`Wiederhergestellt und als neue aktuelle Version gespeichert · v${r.config.version}`);await loadHistory()}catch(e){alert(e.message)}};$('historyRefresh').onclick=loadHistory;

function activateMode(mode){if(!['classification','correspondent','app'].includes(mode))mode='classification';document.querySelectorAll('.mode-switch button').forEach(b=>b.classList.toggle('active',b.dataset.mode===mode));document.querySelectorAll('.mode').forEach(x=>x.classList.toggle('active',x.id===`mode-${mode}`));try{localStorage.setItem('paperlessPromptStudioMode',mode)}catch{}}
function activateSubtab(mode,id){const nav=document.querySelector(`.subtabs[data-mode-tabs="${mode}"]`);const page=$(id);if(!nav||!page||page.dataset.pageMode!==mode)return;nav.querySelectorAll('button').forEach(b=>b.classList.toggle('active',b.dataset.subtab===id));document.querySelectorAll(`.subtab-page[data-page-mode="${mode}"]`).forEach(x=>x.classList.toggle('active',x.id===id));try{localStorage.setItem(`paperlessPromptStudioTab:${mode}`,id)}catch{}}
document.querySelectorAll('.mode-switch button').forEach(b=>b.onclick=()=>activateMode(b.dataset.mode));
document.querySelectorAll('.subtabs button').forEach(b=>b.onclick=()=>{const mode=b.closest('.subtabs').dataset.modeTabs;activateSubtab(mode,b.dataset.subtab)});
let initialMode='classification';try{initialMode=localStorage.getItem('paperlessPromptStudioMode')||initialMode}catch{}activateMode(initialMode);
for(const [mode,fallback] of [['classification','prompt'],['correspondent','corr-prompt'],['app','app-connections']]){let tab=fallback;try{tab=localStorage.getItem(`paperlessPromptStudioTab:${mode}`)||fallback}catch{}activateSubtab(mode,tab)}
init();
loadCorrespondent();
loadApp();
</script>
</body>
</html>'''


def response(handler, status, data, content_type="application/json; charset=utf-8"):
    if isinstance(data, (dict, list)):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    elif isinstance(data, str):
        body = data.encode("utf-8")
    else:
        body = bytes(data)
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def body_json(handler):
    length = int(handler.headers.get("Content-Length", "0"))
    if length > 2_000_000:
        raise ValueError("Request zu groß")
    raw = handler.rfile.read(length) if length else b"{}"
    return json.loads(raw.decode("utf-8"))


def draft_config(payload):
    cfg = payload.get("config")
    if cfg is None:
        cfg = load_config()
    return validate_config(cfg)


def preview_for(doc_id, config):
    tax = client.taxonomy()
    doc = client.document(doc_id)
    rendered = render_prompts(doc, tax, config)
    return tax, doc, rendered


class Handler(BaseHTTPRequestHandler):
    server_version = "paperless-local-ai-studio/0.1"

    def log_message(self, fmt, *args):
        print(f"[HTTP] {self.address_string()} {fmt % args}", flush=True)

    def _dispatch(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if self.command == "GET" and path == "/":
            return response(self, HTTPStatus.OK, HTML, "text/html; charset=utf-8")

        if self.command == "GET" and path == "/api/app/state":
            cfg = ensure_app_config()
            return response(self, HTTPStatus.OK, {
                "config": cfg,
                "config_sha256": app_config_hash(cfg),
                "history": list_app_history(),
                "token_configured": bool(PAPERLESS_TOKEN),
            })

        if self.command == "GET" and path == "/api/app/history":
            return response(self, HTTPStatus.OK, {"items": list_app_history()})

        if self.command == "POST" and path == "/api/app/validate":
            payload = body_json(self)
            cfg = validate_app_config(payload.get("config"))
            return response(self, HTTPStatus.OK, {
                "ok": True,
                "config_sha256": app_config_hash(cfg),
            })

        if self.command == "POST" and path == "/api/app/save":
            payload = body_json(self)
            cfg = save_app_config(payload.get("config"), source="prompt-ui")
            return response(self, HTTPStatus.OK, {
                "ok": True,
                "config": cfg,
                "config_sha256": app_config_hash(cfg),
                "history": list_app_history(),
                "token_configured": bool(PAPERLESS_TOKEN),
            })

        if self.command == "POST" and path == "/api/app/history/restore":
            payload = body_json(self)
            cfg = restore_app_history(payload.get("file", ""))
            return response(self, HTTPStatus.OK, {
                "ok": True,
                "config": cfg,
                "history": list_app_history(),
                "token_configured": bool(PAPERLESS_TOKEN),
            })

        if self.command == "POST" and path == "/api/app/connections/test":
            payload = body_json(self)
            cfg = validate_app_config(payload.get("config"))
            paperless_url = cfg["connections"]["paperless_url"]
            ollama_url = cfg["connections"]["ollama_url"]

            paperless_result = {"ok": False, "detail": ""}
            if not PAPERLESS_TOKEN:
                paperless_result["detail"] = "PAPERLESS_TOKEN fehlt in der Deployment-Umgebung"
            else:
                try:
                    r = requests.get(
                        paperless_url + "/api/documents/",
                        params={"page_size": 1},
                        headers={
                            "Authorization": f"Token {PAPERLESS_TOKEN}",
                            "Accept": "application/json",
                        },
                        timeout=20,
                    )
                    r.raise_for_status()
                    paperless_result = {"ok": True, "detail": f"HTTP {r.status_code}"}
                except Exception as exc:
                    paperless_result["detail"] = f"{type(exc).__name__}: {exc}"

            ollama_result = {"ok": False, "detail": ""}
            try:
                r = requests.get(ollama_url + "/api/tags", timeout=20)
                r.raise_for_status()
                payload = r.json()
                count = len(payload.get("models", [])) if isinstance(payload, dict) else 0
                ollama_result = {"ok": True, "detail": f"{count} Modell(e) gefunden"}
            except Exception as exc:
                ollama_result["detail"] = f"{type(exc).__name__}: {exc}"

            return response(self, HTTPStatus.OK, {
                "paperless": paperless_result,
                "ollama": ollama_result,
            })

        if self.command == "GET" and path == "/api/state":
            cfg = ensure_config()
            return response(self, HTTPStatus.OK, {
                "config": cfg,
                "placeholders": PLACEHOLDERS,
                "hashes": prompt_hashes(cfg),
                "connections": ensure_app_config()["connections"],
            })

        if self.command == "GET" and path == "/api/health":
            cfg = load_config()
            return response(self, HTTPStatus.OK, {
                "ok": True,
                "config_version": cfg["version"],
                "model": cfg["model"],
            })

        if self.command == "GET" and path == "/api/history":
            return response(self, HTTPStatus.OK, {"items": list_history()})

        if self.command == "POST" and path == "/api/config/validate":
            payload = body_json(self)
            cfg = validate_config(payload.get("config"))
            return response(self, HTTPStatus.OK, {
                "ok": True,
                "config_sha256": prompt_hashes(cfg)["config_sha256"],
            })

        if self.command == "POST" and path == "/api/config/save":
            payload = body_json(self)
            cfg = save_config(payload.get("config"), source="prompt-ui")
            return response(self, HTTPStatus.OK, {
                "ok": True,
                "config": cfg,
                "hashes": prompt_hashes(cfg),
            })

        if self.command == "POST" and path == "/api/history/restore":
            payload = body_json(self)
            cfg = restore_history(payload.get("file", ""))
            return response(self, HTTPStatus.OK, {"ok": True, "config": cfg})

        if self.command == "POST" and path in {"/api/preview", "/api/test"}:
            payload = body_json(self)
            doc_id = int(payload["document_id"])
            cfg = draft_config(payload)
            tax, doc, rendered = preview_for(doc_id, cfg)
            base = {
                "document": {
                    "id": doc.get("id"),
                    "title": doc.get("title"),
                    "created": doc.get("created"),
                },
                "rendered": {
                    "system_prompt": rendered["system_prompt"],
                    "user_prompt": rendered["user_prompt"],
                    "schema": rendered["schema"],
                },
                "taxonomy": {
                    "tags": tax["content_tags"],
                    "document_types": tax["document_types"],
                    "correspondents": tax["correspondents"],
                },
                "meta": {
                    "config_version": cfg["version"],
                    "draft_config_sha256": prompt_hashes(cfg)["config_sha256"],
                    "model": cfg["model"],
                    "num_ctx": cfg["num_ctx"],
                    "num_predict": cfg["num_predict"],
                    "temperature": cfg["temperature"],
                    "think": cfg["think"],
                    "keep_alive": cfg["keep_alive"],
                    "content_chars_used": rendered["content_chars_used"],
                    "content_truncated": rendered["content_truncated"],
                },
            }
            if path == "/api/preview":
                return response(self, HTTPStatus.OK, base)

            with ai_resource_lock("LLM-PROMPT-UI", doc_id):
                result, raw, wall_duration, _payload = call_ollama(rendered, cfg)
            errors = validate_result(result, tax, cfg)
            base.update({
                "suggestion": result,
                "validation_errors": errors,
                "performance": performance_from_raw(raw, wall_duration),
            })
            return response(self, HTTPStatus.OK, base)


        if self.command == "GET" and path == "/api/correspondent/state":
            cfg = ensure_correspondent_config()
            return response(self, HTTPStatus.OK, {
                "config": cfg,
                "placeholders": CORRESPONDENT_PLACEHOLDERS,
                "hashes": correspondent_prompt_hashes(cfg),
                "history": list_correspondent_history(),
            })

        if self.command == "POST" and path == "/api/correspondent/validate":
            payload = body_json(self)
            cfg = validate_correspondent_config(payload.get("config"))
            return response(self, HTTPStatus.OK, {
                "ok": True,
                "config_sha256": correspondent_prompt_hashes(cfg)["config_sha256"],
            })

        if self.command == "POST" and path == "/api/correspondent/save":
            payload = body_json(self)
            cfg = save_correspondent_config(
                payload.get("config"),
                source="prompt-ui",
            )
            return response(self, HTTPStatus.OK, {
                "ok": True,
                "config": cfg,
                "hashes": correspondent_prompt_hashes(cfg),
            })

        if self.command == "POST" and path == "/api/correspondent/history/restore":
            payload = body_json(self)
            cfg = restore_correspondent_history(payload.get("file", ""))
            return response(self, HTTPStatus.OK, {
                "ok": True,
                "config": cfg,
            })

        if self.command == "POST" and path in {
            "/api/correspondent/preview",
            "/api/correspondent/test",
        }:
            payload = body_json(self)
            doc_id = int(payload["document_id"])
            cfg = validate_correspondent_config(payload.get("config"))
            tax = client.taxonomy()
            doc = client.document(doc_id)
            rendered = render_correspondent_prompts(doc, tax, cfg)

            base = {
                "document": {
                    "id": doc.get("id"),
                    "title": doc.get("title"),
                    "created": doc.get("created"),
                },
                "rendered": {
                    "system_prompt": rendered["system_prompt"],
                    "user_prompt": rendered["user_prompt"],
                    "schema": rendered["schema"],
                },
                "meta": {
                    "config_version": cfg["version"],
                    "draft_config_sha256": correspondent_prompt_hashes(cfg)["config_sha256"],
                    "enabled_in_draft": cfg["enabled"],
                    "model": cfg["model"],
                    "num_ctx": cfg["num_ctx"],
                    "num_predict": cfg["num_predict"],
                    "temperature": cfg["temperature"],
                    "think": cfg["think"],
                    "keep_alive": cfg["keep_alive"],
                    "content_char_limit": cfg["content_char_limit"],
                    "content_head_ratio": cfg["content_head_ratio"],
                    "content_chars_used": rendered["content_chars_used"],
                    "content_truncated": rendered["content_truncated"],
                    "existing_correspondents": len(tax["correspondents"]),
                },
            }

            if path == "/api/correspondent/preview":
                return response(self, HTTPStatus.OK, base)

            with ai_resource_lock("LLM-CORRESPONDENT-UI", doc_id):
                result, raw, wall_duration, _payload = (
                    call_correspondent_ollama(rendered, cfg)
                )

            errors = validate_correspondent_result(result)
            base.update({
                "suggestion": result,
                "validation_errors": errors,
                "performance": correspondent_performance_from_raw(
                    raw,
                    wall_duration,
                ),
            })
            return response(self, HTTPStatus.OK, base)

        return response(self, HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def do_GET(self):
        try:
            self._dispatch()
        except Exception as e:
            traceback.print_exc()
            response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"{type(e).__name__}: {e}"})

    def do_POST(self):
        try:
            self._dispatch()
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            response(self, HTTPStatus.BAD_REQUEST, {"error": f"{type(e).__name__}: {e}"})
        except Exception as e:
            traceback.print_exc()
            response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"{type(e).__name__}: {e}"})


if __name__ == "__main__":
    app_cfg = ensure_app_config()
    cfg = ensure_config()
    print(
        f"paperless-local-ai Studio auf http://{HOST}:{PORT} · AppConfig v{app_cfg['version']} · PromptConfig v{cfg['version']}",
        flush=True,
    )
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
