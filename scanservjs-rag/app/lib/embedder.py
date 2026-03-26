"""
Ollama Embedding-Client für nomic-embed-text (oder beliebiges Ollama-Modell).
Nutzt httpx für synchrone Requests mit Retry-Logik.
"""

import time
import httpx


class OllamaEmbedder:
    def __init__(self, ollama_url: str, model: str = "nomic-embed-text"):
        self.url = ollama_url.rstrip("/")
        self.model = model
        self._client = httpx.Client(timeout=60.0)

    def embed(self, text: str) -> list[float]:
        """Erstellt einen Embedding-Vektor für den gegebenen Text.

        Versucht bis zu 3 Mal bei Verbindungsfehlern.
        Gibt leere Liste zurück bei Dauerfehler.
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
                time.sleep(2 ** attempt)
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(
                    f"Ollama Embeddings HTTP {exc.response.status_code}: {exc.response.text}"
                ) from exc
            except httpx.RequestError as exc:
                if attempt == 3:
                    return []
                time.sleep(2 ** attempt)

        return []

    def check_connection(self) -> tuple[bool, str]:
        """Prüft ob Ollama erreichbar ist. Gibt (ok, message) zurück."""
        try:
            response = self._client.get(f"{self.url}/api/tags", timeout=5.0)
            response.raise_for_status()
            models = [m["name"] for m in response.json().get("models", [])]
            return True, f"Verbunden — {len(models)} Modelle verfügbar"
        except httpx.RequestError as exc:
            return False, f"Verbindung fehlgeschlagen: {exc}"
        except httpx.HTTPStatusError as exc:
            return False, f"HTTP {exc.response.status_code}"

    def list_models(self) -> list[str]:
        """Gibt Liste aller verfügbaren Ollama-Modelle zurück."""
        try:
            response = self._client.get(f"{self.url}/api/tags", timeout=5.0)
            response.raise_for_status()
            return [m["name"] for m in response.json().get("models", [])]
        except Exception:
            return []

    def close(self):
        self._client.close()
