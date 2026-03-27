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
