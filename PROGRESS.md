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
