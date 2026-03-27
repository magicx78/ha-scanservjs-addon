"""
Ollama Embedding-Client fuer nomic-embed-text (oder beliebiges Ollama-Modell).
Nutzt httpx fuer synchrone Requests mit Retry-Logik.
"""

import time

import httpx


class OllamaEmbedder:
    def __init__(self, ollama_url: str, model: str = "nomic-embed-text"):
        self.url = ollama_url.rstrip("/")
        self.model = model
        self._client = httpx.Client(timeout=60.0)

    def embed(self, text: str) -> list[float]:
        """Erstellt einen Embedding-Vektor fuer den gegebenen Text.

        Versucht bis zu 3 Mal bei Verbindungsfehlern.
        Gibt leere Liste zurueck bei Dauerfehler.
        """
        endpoint = f"{self.url}/api/embeddings"
        payload = {"model": self.model, "prompt": text}

        for attempt in range(1, 4):
            try:
                response = self._client.post(endpoint, json=payload)
                response.raise_for_status()
                data = response.json()
                return data.get("embedding", [])
            except httpx.TimeoutException:
                if attempt == 3:
                    return []
                time.sleep(2**attempt)
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(
                    f"Ollama Embeddings HTTP {exc.response.status_code}: {exc.response.text}"
                ) from exc
            except httpx.RequestError:
                if attempt == 3:
                    return []
                time.sleep(2**attempt)

        return []

    def check_connection(self) -> tuple[bool, str]:
        """Prueft ob Ollama erreichbar ist. Gibt (ok, message) zurueck."""
        try:
            response = self._client.get(f"{self.url}/api/tags", timeout=5.0)
            response.raise_for_status()
            models = [m["name"] for m in response.json().get("models", [])]
            return True, f"Verbunden - {len(models)} Modelle verfuegbar"
        except httpx.RequestError as exc:
            return False, f"Verbindung fehlgeschlagen: {exc}"
        except httpx.HTTPStatusError as exc:
            return False, f"HTTP {exc.response.status_code}"

    def list_models(self) -> list[str]:
        """Gibt Liste aller verfuegbaren Ollama-Modelle zurueck."""
        try:
            return [m["name"] for m in self._fetch_model_entries()]
        except Exception:
            return []

    def list_models_with_chat_capability(self) -> list[dict]:
        """Returns model list with a chat-capable flag and reason."""
        models: list[dict] = []
        try:
            entries = self._fetch_model_entries()
        except Exception:
            return []

        for entry in entries:
            name = str(entry.get("name") or "").strip()
            if not name:
                continue
            is_chat_capable, reason = self._is_chat_capable(entry)
            models.append(
                {
                    "name": name,
                    "chat_capable": is_chat_capable,
                    "reason": reason,
                }
            )
        return models

    def list_chat_models(self) -> list[str]:
        """Returns preferred chat-capable models (filters obvious embedding-only models)."""
        try:
            models = self.list_models_with_chat_capability()
        except Exception:
            return []

        all_names = [m["name"] for m in models]
        chat_models = [m["name"] for m in models if m.get("chat_capable")]
        return chat_models or all_names

    def _fetch_model_entries(self) -> list[dict]:
        response = self._client.get(f"{self.url}/api/tags", timeout=5.0)
        response.raise_for_status()
        return response.json().get("models", [])

    @staticmethod
    def _is_chat_capable(model_entry: dict) -> tuple[bool, str]:
        name = str(model_entry.get("name") or "").strip()
        lower_name = name.lower()
        details = model_entry.get("details") or {}
        families = details.get("families") or []
        families_text = " ".join(str(f).lower() for f in families)

        # Embedding models often fail on /api/chat with HTTP 400.
        if "embed" in lower_name or "embedding" in lower_name:
            return False, "Embedding-Modell"
        if "bert" in families_text or "embed" in families_text:
            return False, "Embedding-Familie"
        return True, ""

    def close(self):
        self._client.close()
