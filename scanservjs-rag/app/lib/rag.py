"""
RAG engine with streaming events for progressive UI rendering.
"""

import json
import random
import time

import httpx


SYSTEM_PROMPT = """\
Du bist ein hilfreicher Dokumenten-Assistent. Dir werden relevante Textausschnitte aus gescannten Dokumenten gegeben.
Beantworte die Frage des Nutzers ausschliesslich auf Basis der bereitgestellten Dokumentenausschnitte.

Regeln:
- Antworte auf Deutsch, praezise und strukturiert
- Nenne die Quelle (Dateiname + Seite), wenn du dich auf ein Dokument beziehst
- Wenn die Antwort nicht in den Ausschnitten steht, sage das klar
- Keine Spekulationen oder erfundene Fakten
- Maximal 300 Woerter pro Antwort
"""

REFINE_PROMPT = """\
Du erhaeltst eine bestehende Antwort und zusaetzliche Quellen.
Aktualisiere die Antwort nur dort, wo die neuen Quellen eine praezisere oder ergaenzende Information liefern.

Regeln:
- Antworte auf Deutsch, praezise und strukturiert
- Nutze nur Informationen aus den bereitgestellten Quellen
- Behalte bereits korrekte Informationen bei
- Ergaenze fehlende Fakten knapp
- Nenne Quellen (Dateiname + Seite) bei konkreten Aussagen
- Maximal 320 Woerter
"""


def _build_context(chunks: list[dict]) -> str:
    parts = []
    for i, chunk in enumerate(chunks, start=1):
        fname = chunk.get("filename", "?")
        page = chunk.get("page", "?")
        score = chunk.get("relevance_score", 0)
        text = chunk.get("text", "")
        parts.append(f"[Quelle {i}: {fname}, Seite {page}, Relevanz {score:.0%}]\n{text}")
    return "\n\n---\n\n".join(parts)


class RAGEngine:
    def __init__(
        self,
        ollama_url: str,
        llm_model: str = "qwen2.5:14b",
        use_claude: bool = False,
        anthropic_api_key: str = "",
        max_retries: int = 3,
        retry_base_seconds: float = 0.4,
        retry_jitter_seconds: float = 0.25,
    ):
        self.ollama_url = ollama_url.rstrip("/")
        self.llm_model = llm_model
        self.use_claude = use_claude and bool(anthropic_api_key)
        self.anthropic_api_key = anthropic_api_key
        self.max_retries = max(1, int(max_retries))
        self.retry_base_seconds = max(0.05, float(retry_base_seconds))
        self.retry_jitter_seconds = max(0.0, float(retry_jitter_seconds))
        self._client = httpx.Client(
            timeout=httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)
        )

    def answer(self, question: str, context_chunks: list[dict], stream_placeholder=None) -> str:
        if not context_chunks:
            return (
                "Keine relevanten Dokumente fuer diese Frage gefunden. "
                "Bitte stelle sicher, dass Dokumente indexiert sind."
            )

        full_text = ""
        for event in self.answer_stream(question, context_chunks):
            if event["type"] == "token":
                full_text += event["content"]
                if stream_placeholder:
                    stream_placeholder.markdown(full_text + "|")
            elif event["type"] == "done":
                full_text = event.get("content", full_text)
                if stream_placeholder:
                    stream_placeholder.markdown(full_text)
                return full_text or "Keine Antwort erhalten."
            elif event["type"] == "error":
                if stream_placeholder:
                    stream_placeholder.error(event["content"])
                return event["content"]
            elif event["type"] == "cancelled":
                return event["content"]
        return full_text or "Keine Antwort erhalten."

    def answer_stream(
        self,
        question: str,
        context_chunks: list[dict],
        mode: str = "initial",
        current_answer: str = "",
        cancel_check=None,
    ):
        """Structured stream events:
        {"type":"token","content":"..."}
        {"type":"done","content":"..."}
        {"type":"error","content":"..."}
        {"type":"meta","content":"..."}
        {"type":"cancelled","content":"..."}
        """
        if callable(cancel_check) and cancel_check():
            yield {"type": "cancelled", "content": "Anfrage abgebrochen."}
            return

        if not context_chunks:
            yield {
                "type": "done",
                "content": (
                    "Keine relevanten Dokumente fuer diese Frage gefunden. "
                    "Bitte stelle sicher, dass Dokumente indexiert sind."
                ),
            }
            return

        context = _build_context(context_chunks)
        if mode == "refine":
            system_prompt = REFINE_PROMPT
            user_message = (
                f"Bestehende Antwort:\n{current_answer}\n\n"
                f"Zusaetzliche Dokumentenausschnitte:\n\n{context}\n\n"
                f"Frage: {question}\n\n"
                "Bitte liefere eine aktualisierte Gesamtantwort."
            )
        else:
            system_prompt = SYSTEM_PROMPT
            user_message = f"Dokumentenausschnitte:\n\n{context}\n\nFrage: {question}"

        if self.use_claude:
            try:
                text = self._answer_claude(user_message)
                yield {"type": "done", "content": text}
            except Exception as exc:  # pragma: no cover - defensive
                yield {"type": "error", "content": f"Claude-Fehler: {exc}"}
            return

        yield from self._stream_ollama(
            user_message=user_message,
            system_prompt=system_prompt,
            cancel_check=cancel_check,
        )

    def _stream_ollama(
        self,
        user_message: str,
        system_prompt: str = SYSTEM_PROMPT,
        cancel_check=None,
    ):
        endpoint = f"{self.ollama_url}/api/chat"
        payload = {
            "model": self.llm_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "stream": True,
            "options": {
                "temperature": 0.1,
                "num_predict": 400,
            },
        }

        full_text = ""
        for attempt in range(1, self.max_retries + 1):
            if callable(cancel_check) and cancel_check():
                yield {"type": "cancelled", "content": "Anfrage abgebrochen."}
                return
            try:
                with self._client.stream("POST", endpoint, json=payload) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if callable(cancel_check) and cancel_check():
                            response.close()
                            yield {"type": "cancelled", "content": "Anfrage abgebrochen."}
                            return
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        token = chunk.get("message", {}).get("content", "")
                        if token:
                            full_text += token
                            yield {"type": "token", "content": token}
                        if chunk.get("done"):
                            break
                yield {"type": "done", "content": full_text or "Keine Antwort erhalten."}
                return
            except (httpx.TimeoutException, httpx.RequestError) as exc:
                if attempt < self.max_retries and not full_text:
                    delay = self._retry_delay(attempt)
                    yield {
                        "type": "meta",
                        "content": f"Netzwerkproblem, erneuter Versuch {attempt + 1}/{self.max_retries} in {delay:.1f}s...",
                    }
                    time.sleep(delay)
                    continue
                if isinstance(exc, httpx.TimeoutException):
                    yield {
                        "type": "error",
                        "content": (
                            "Zeitueberschreitung (300s). Das Modell ist wahrscheinlich noch nicht geladen. "
                            "Tipp: Modell vorwaermen und erneut suchen."
                        ),
                    }
                else:
                    yield {"type": "error", "content": f"Verbindungsfehler zu Ollama: {exc}"}
                return
            except httpx.HTTPStatusError as exc:
                status_code = int(exc.response.status_code) if exc.response else 0
                if (
                    self._is_transient_status(status_code)
                    and attempt < self.max_retries
                    and not full_text
                ):
                    delay = self._retry_delay(attempt)
                    yield {
                        "type": "meta",
                        "content": f"Backend {status_code}, erneuter Versuch {attempt + 1}/{self.max_retries} in {delay:.1f}s...",
                    }
                    time.sleep(delay)
                    continue
                yield {
                    "type": "error",
                    "content": f"Ollama HTTP-Fehler {exc.response.status_code}: {exc.response.text[:200]}",
                }
                return

    def _retry_delay(self, attempt: int) -> float:
        backoff = self.retry_base_seconds * (2 ** (attempt - 1))
        jitter = random.uniform(0.0, self.retry_jitter_seconds)
        return backoff + jitter

    @staticmethod
    def _is_transient_status(status_code: int) -> bool:
        return status_code in {408, 425, 429, 500, 502, 503, 504}

    def _answer_ollama(self, user_message: str, stream_placeholder=None) -> str:
        full_text = ""
        for event in self._stream_ollama(
            user_message=user_message,
            system_prompt=SYSTEM_PROMPT,
            cancel_check=None,
        ):
            if event["type"] == "token":
                full_text += event["content"]
                if stream_placeholder:
                    stream_placeholder.markdown(full_text + "|")
            elif event["type"] == "done":
                final = event.get("content", full_text)
                if stream_placeholder:
                    stream_placeholder.markdown(final)
                return final or "Keine Antwort erhalten."
            elif event["type"] == "error":
                if stream_placeholder:
                    stream_placeholder.error(event["content"])
                return event["content"]
            elif event["type"] == "cancelled":
                return event["content"]
        return full_text or "Keine Antwort erhalten."

    def _answer_claude(self, user_message: str) -> str:
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=self.anthropic_api_key)
            message = client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=600,
                timeout=30.0,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
            return message.content[0].text.strip()
        except ImportError:
            return self._answer_ollama(user_message)
        except Exception:  # pragma: no cover - fallback path
            return self._answer_ollama(user_message)

    def close(self):
        self._client.close()
