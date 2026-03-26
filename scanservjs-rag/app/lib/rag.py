"""
RAG-Engine: Generiert Antworten auf Basis von Kontext-Chunks.

Primär: Ollama (qwen2.5:14b oder konfiguriertes Modell) — vollständig lokal.
Fallback: Claude API (claude-haiku-4-5) wenn USE_CLAUDE=true und API-Key gesetzt.
"""

import os
import httpx


SYSTEM_PROMPT = """\
Du bist ein hilfreicher Dokumenten-Assistent. Dir werden relevante Textausschnitte aus gescannten Dokumenten gegeben.
Beantworte die Frage des Nutzers ausschließlich auf Basis der bereitgestellten Dokumentenausschnitte.

Regeln:
- Antworte auf Deutsch, präzise und strukturiert
- Nenne die Quelle (Dateiname + Seite) wenn du dich auf ein Dokument beziehst
- Wenn die Antwort nicht in den Ausschnitten steht, sage das klar
- Keine Spekulationen oder erfundene Fakten
- Maximal 300 Wörter pro Antwort
"""


def _build_context(chunks: list[dict]) -> str:
    """Formatiert Kontext-Chunks für den LLM-Prompt."""
    parts = []
    for i, chunk in enumerate(chunks, start=1):
        fname = chunk.get("filename", "?")
        page = chunk.get("page", "?")
        score = chunk.get("relevance_score", 0)
        text = chunk.get("text", "")
        parts.append(
            f"[Quelle {i}: {fname}, Seite {page}, Relevanz {score:.0%}]\n{text}"
        )
    return "\n\n---\n\n".join(parts)


class RAGEngine:
    def __init__(
        self,
        ollama_url: str,
        llm_model: str = "qwen2.5:14b",
        use_claude: bool = False,
        anthropic_api_key: str = "",
    ):
        self.ollama_url = ollama_url.rstrip("/")
        self.llm_model = llm_model
        self.use_claude = use_claude and bool(anthropic_api_key)
        self.anthropic_api_key = anthropic_api_key
        self._client = httpx.Client(timeout=120.0)

    def answer(self, question: str, context_chunks: list[dict]) -> str:
        """Generiert eine Antwort auf `question` basierend auf `context_chunks`."""
        if not context_chunks:
            return "Keine relevanten Dokumente für diese Frage gefunden. Bitte stelle sicher, dass Dokumente indexiert sind."

        context = _build_context(context_chunks)
        user_message = (
            f"Dokumentenausschnitte:\n\n{context}\n\n"
            f"Frage: {question}"
        )

        if self.use_claude:
            return self._answer_claude(user_message)
        return self._answer_ollama(user_message)

    def _answer_ollama(self, user_message: str) -> str:
        """Ollama Chat-Completion (primär, vollständig lokal)."""
        endpoint = f"{self.ollama_url}/api/chat"
        payload = {
            "model": self.llm_model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 600,
            },
        }

        try:
            response = self._client.post(endpoint, json=payload)
            response.raise_for_status()
            data = response.json()
            return data.get("message", {}).get("content", "Keine Antwort erhalten.")
        except httpx.TimeoutException:
            return "Zeitüberschreitung bei der Anfrage an Ollama. Das Modell braucht möglicherweise länger zum Laden."
        except httpx.RequestError as exc:
            return f"Verbindungsfehler zu Ollama: {exc}"
        except httpx.HTTPStatusError as exc:
            return f"Ollama HTTP-Fehler {exc.response.status_code}: {exc.response.text[:200]}"

    def _answer_claude(self, user_message: str) -> str:
        """Claude API Fallback (cloud, braucht Internet + API-Key)."""
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
        except Exception as exc:
            # Bei Claude-Fehler auf Ollama zurückfallen
            return self._answer_ollama(user_message)

    def close(self):
        self._client.close()
