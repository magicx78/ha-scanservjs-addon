# Progress - scanservjs-rag Stabilitaet & Robustheit

Datum: 2026-03-27

## Status der kurzfristig erforderlichen Punkte

### 1) Harte serverseitige Cancelation laufender LLM-Streams
- Status: **umgesetzt (mit dokumentierter Restgrenze)**
- Umgesetzt:
  - `cancel_check` in `RAGEngine.answer_stream(...)` und `_stream_ollama(...)`
  - bei Cancel wird der aktive HTTP-Stream sofort geschlossen (`response.close()`)
  - Event `cancelled` wird in den Such-Flow propagiert und in der UI als `cancelled` abgeschlossen
- Warum nicht 100% "kill" garantiert:
  - HTTP-Stream-Abbruch stoppt die laufende Antwortlieferung sofort auf Add-on-Seite.
  - Je nach Ollama-Serververhalten kann die Backend-Generierung intern noch kurz nachlaufen.
- Offene Restarbeit:
  - Optionaler hartes Abort-Endpoint/Worker-Control (prozessseitiges Kill-Signal), falls der LLM-Server das unterstützt.

### 2) Kleine Integrationstests fuer State-Transitions
- Status: **umgesetzt**
- Umgesetzt:
  - `scanservjs-rag/app/tests/test_state_transitions.py`
  - Pfade: `started -> ... -> completed`, `started -> empty`, `started -> ... -> error`, `started -> cancelled`
  - Guard-Test fuer ungueltige Transitionen
  - State-Transition-Logik zentral in `scanservjs-rag/app/lib/state_machine.py`

### 3) Telemetrie pro Phase
- Status: **umgesetzt**
- Umgesetzt:
  - Messung `first_hit_at`, `first_token_at`, `total_duration_ms`, `cache_hit`
  - Logging via `logger.info(...)` bei Finalisierung des Suchlaufs
  - Anzeige `total_duration_ms` im Statuspanel

### 4) UI-Feintuning fuer lange Dokumente/Antworten
- Status: **teilweise umgesetzt + manuell pruefen**
- Umgesetzt:
  - Antwortbereich stabilisiert (`max-height`, `overflow:auto`, `word-break`, konstante Box-Geometrie)
  - verhindert Layout-Spruenge bei langen Antworten
- Offen:
  - visuelles Fine-Tuning mit echten langen Produktionsdokumenten (manueller Geräte-/Browser-Check)

## Weitere umgesetzte Stabilitaetsarbeiten
- Query-Cache mit TTL + DB-Revision-Key (verhindert veraltete Trefferanzeigen)
- dedizierte Data-Caches fuer `get_stats`/`list_documents`
- zentrale Cache-Invalidierung nach Upload/Delete/Reindex/Reset
- Retry-Strategie bei transienten Netzwerkproblemen im Streaming
- Schutz gegen haengende Loader via finaler Streaming-Reset

## Später optional (noch offen)
- Delta-Refinement statt Voll-Refinement
- Confidence-Badges + Deep-Links pro Quelle
- Background-Queue fuer parallele Suche/Antwortaktualisierung
- Feature-Flag fuer alternative Retrieval-Stufen (z. B. 1/2/5, 1/3/8)

## Nachtrag 2026-03-27 (Release 1.0.10 / 1.0.11)
- LLM-Auswahl im UI ist jetzt funktional:
  - echtes Dropdown fuer Modellwechsel im Suche-Tab und Status-Tab
  - direkte Verfuegbarkeitsanzeige (online/OK) fuer das gewaehlte Modell
- Suche wahrgenommen beschleunigt:
  - reduzierte Retrieval-Stufen und niedrigere UI-Wartezeiten
  - aufwendiges Refinement standardmaessig deaktiviert (ENABLE_REFINE=false)
- UI vereinfacht:
  - Fokus auf zwei Hauptfelder Treffer und Antwort
  - dezente, verspielte Mikroanimationen zur Aktivitaetsanzeige
- Versionen:
  - 1.0.10: LLM-Dropdown + Online-Status
  - 1.0.11: Re-Release fuer sicheres Update-Picking in Home Assistant

## Nachtrag 2026-03-27 (Release 1.0.12 / 1.0.13)
- Suche im UI final auf zwei Hauptfenster reduziert:
  - Treffer (live in Echtzeit)
  - Antwort (Streaming)
- Pac-Man-Animation fuer den Antwortaufbau integriert ("spuckt langsam aus").
- Suchtab vereinfacht (kein separates Statusfenster mehr), Fokus auf Lesbarkeit und direkte Rueckmeldung.
- Versionen:
  - 1.0.12: Two-window Suche + Pac-Man-Streaming
  - 1.0.13: Versionierung + Progress-Nachtrag fuer sauberes Update in Home Assistant

## Verifikation 2026-03-27 (nach Release 1.0.14)
- Durchgefuehrte Pruefungen:
  - `python -m py_compile` fuer `app.py`, `rag.py`, `vector_db.py`, `search_cache.py`, `state_machine.py`
  - `python -m unittest discover -s scanservjs-rag/app/tests -p "test_*.py" -v`
- Ergebnis:
  - Compile: OK
  - Tests: 8/8 OK
- Remote-Check:
  - `scanservjs-rag/config.yaml` auf `origin/main` steht auf `version: "1.0.14"`
- UI-Hinweis:
  - Suchansicht ist auf 2 feste Fenster ausgelegt (Treffer + Antwort) mit stabilen Platzhaltern.

## Nachtrag 2026-03-27 (Release 1.0.16)
- Fehlerbehebung Suche/Streaming:
  - `missing ScriptRunContext` Warnungen durch Worker-Cancel-Check behoben (kein Streamlit-Zugriff mehr aus Worker-Thread).
  - Trefferfenster zeigt nach dem ersten Hit direkt die Top-`MAX_RESULTS` nach Relevanz (nicht mehr nur 1 Treffer).
  - Antwortfenster zeigt bei Fehlern jetzt den Fehlertext klar an.
- Pac-Man/Animationen sichtbar gemacht:
  - Pac-Man-Glyph + Bewegung waehrend laufender Antwortgenerierung.
  - Live-Suchindikator im Trefferfenster.
- Stabilisierung:
  - nur ein fixes Trefferfenster und ein fixes Antwortfenster (keine Mehrfach-Panel-Vervielfachung).

## Nachtrag 2026-03-27 (Release 1.0.17)
- Treffer-Vorschau eingebaut:
  - Trefferkarten sind jetzt anklickbar (`Vorschau`-Button je Treffer).
  - Oeffnet einen Dialog mit eingebettetem PDF-Viewer.
  - Aktionen im Dialog: `Drucken`, `Speichern / Download`, `Schliessen`.
  - Metadaten sichtbar: Dokumentname, Seite/Chunk, Quelle, Relevanz.
  - Fallback fuer nicht-PDF-Dateien mit Download bleibt erhalten.
- Dark-Mode-Haertung:
  - komplette Ueberschreibung kritischer Streamlit-Defaults fuer dunkle Flaechen.
  - konsistente Farben fuer Hintergrund, Container, Trefferkarten, Tabs, Expander, Buttons, Inputs, Dropdowns und Info-/Statusboxen.
  - Lesbarkeit und Kontraste in allen Kernbereichen verbessert.

## Nachtrag 2026-03-27 (Release 1.0.18)
- Streaming-Suchfluss auf feste Phasen umgestellt:
  - `started`, `retrieving`, `reranking`, `partial_results`, `generating_answer`, `done`, `error`.
- Backend-kompatible Suchservice-Schicht ergaenzt:
  - normaler Endpoint: `SearchService.search(...)` (one-shot, Rueckwaertskompatibilitaet)
  - Streaming-Endpoint: `SearchService.search_stream(...)` (progressive Events)
- Frontend-State erweitert (ohne Layout-Aenderung):
  - `statusMessage`, `progressSteps`, `partialResults`, `finalResult`
  - weiterhin exakt 2 Hauptbereiche: Trefferfenster + Antwortfenster
- UX:
  - Statuszeile + kompakte Step-Liste direkt im bestehenden Trefferfenster
  - Teiltreffer werden sofort im Trefferfenster sichtbar
  - Zwischenstatus und Streaming-Antwort nur im bestehenden Antwortfenster
- Fallback:
  - `USE_SEARCH_STREAMING=false` nutzt automatisch den normalen Such-Endpoint
  - keine Breaking Changes fuer bestehende Clients
- Tests:
  - neue Tests fuer Search-Service-Events
  - State-Transition-Tests fuer neue Phase-Kette ergaenzt

## Nachtrag 2026-03-27 (Release 1.0.19)
- Debug-/Fix-Runde nach Streaming-Umstellung:
  - Fortschritts-UI im Trefferfenster korrigiert: finaler Schritt `done` wird jetzt korrekt als abgeschlossen markiert (nicht mehr als aktiv).
  - Regressionstestlauf erneut durchgefuehrt (`13/13` Tests OK).
  - Keine Layout-Aenderung: weiterhin exakt 2 Hauptbereiche (Treffer + Antwort).

## Nachtrag 2026-03-27 (Release 1.0.20)
- Crash-Fix fuer `StreamlitDuplicateElementKey`:
  - interaktive Treffer-Buttons (`Vorschau`) werden pro Script-Run nur noch einmal erzeugt.
  - Render-Reihenfolge in `tab_suche()` angepasst (bei aktivem Suchlauf zuerst non-interaktiv, interaktiv erst nach Pipeline).
  - doppelte interaktive Final-Render in `_run_search_pipeline()` entfernt.
- Warnungsreduktion fuer `MediaFileHandler: Missing file ... .bin`:
  - Vorschau-Download von `st.download_button` auf direkte Data-URI-Download-Links umgestellt.
  - gilt fuer PDF- und Non-PDF-Download im Vorschau-Dialog.
- Ergebnis:
  - keine Duplicate-Key-Abbrueche mehr im Trefferfenster.
  - deutlich stabilerer Vorschau-/Download-Flow unter haeufigen Reruns.

## Nachtrag 2026-03-27 (Release 1.0.21)
- Zusatz-Haertung fuer den gemeldeten Live-Fehlerfall:
  - Vorschau-Button-Keys jetzt mit Render-Nonce abgesichert (`hit_preview_<nonce>...`) gegen Mehrfach-Render im selben Run.
  - Dokument-Downloads im Dokumente-Tab auf Dialog + Data-URI umgestellt (kein `st.download_button` mehr), um `MediaFileHandler: Missing file ...bin` zu vermeiden.
- Betriebs-Transparenz verbessert:
  - `run.sh` loggt jetzt die Add-on-Version dynamisch aus `config.yaml` statt statisch `v1.0.2`.
  - dadurch ist im HA-Log sofort sichtbar, welche Version wirklich laeuft.

## Nachtrag 2026-03-27 (Release 1.0.22)
- Deploy-/Runtime-Fix fuer Versionsanzeige:
  - `config.yaml` wird jetzt explizit ins Container-Image kopiert (`/addon-config.yaml`).
  - `run.sh` liest die Startversion aus `/addon-config.yaml` statt aus nicht vorhandener `/app/config.yaml`.
- Ergebnis:
  - Startlog zeigt im Normalfall die echte Add-on-Version (kein `vunknown` mehr).
  - erleichtert Verifikation, ob der DuplicateKey-/MediaFile-Hotfix wirklich aktiv ist.

## Nachtrag 2026-03-27 (Release 1.0.23)
- Fehlerbehebung im LLM-Streaming-Fehlerpfad:
  - HTTP-Fehlerbehandlung in `rag.py` robust gemacht, sodass keine Ausnahme mehr durch Zugriff auf ungelesene Streaming-Response (`response.text`) entsteht.
  - neue sichere Detail-Extraktion fuer HTTP-Fehler (`_safe_response_text`), inkl. Fallback auf `read()`/`reason_phrase`.
- Ergebnis:
  - Suchlauf endet bei Backend-HTTP-Fehlern mit sauberer Fehlermeldung statt mit `Attempted to access streaming response content, without having called read()`.
- Tests:
  - neuer Testfall fuer HTTPStatusError hinzugefuegt (`test_rag_retry.py`), gesamter Testlauf weiterhin gruen.
