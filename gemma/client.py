from __future__ import annotations

import time
from typing import Any

import httpx


class OllamaError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout: float = 45) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.last_latency_ms: float | None = None

    def chat(self, system: str, user: str, json_output: bool = True) -> str:
        started = time.perf_counter()
        try:
            payload: dict[str, Any] = {
                "model": self.model,
                "stream": False,
                "think": False,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "options": {"temperature": 0},
            }
            if json_output:
                payload["format"] = "json"
            response = httpx.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            content = data.get("message", {}).get("content")
            if not isinstance(content, str) or not content.strip():
                raise OllamaError("Ollama returned an empty or malformed response")
            return content
        except httpx.ConnectError as exc:
            raise OllamaError("Ollama is not reachable. Start Ollama and try again.") from exc
        except httpx.TimeoutException as exc:
            raise OllamaError("The local model request timed out.") from exc
        except httpx.RequestError as exc:
            raise OllamaError(f"Ollama request failed locally: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            detail = "The configured model may not be installed." if exc.response.status_code == 404 else "Ollama returned an HTTP error."
            raise OllamaError(detail) from exc
        except (ValueError, TypeError) as exc:
            raise OllamaError("Ollama returned malformed JSON.") from exc
        finally:
            self.last_latency_ms = (time.perf_counter() - started) * 1000

    def health_check(self) -> dict[str, Any]:
        result: dict[str, Any] = {"reachable": False, "model_available": False, "generation_ok": False, "model": self.model}
        try:
            response = httpx.get(f"{self.base_url}/api/tags", timeout=min(self.timeout, 5))
            response.raise_for_status()
            result["reachable"] = True
            names = [item.get("name") for item in response.json().get("models", [])]
            result["model_available"] = self.model in names
            if result["model_available"]:
                self.chat("Reply with JSON only.", 'Return {"ok": true}.')
                result["generation_ok"] = True
        except Exception as exc:
            result["error"] = str(exc)
        return result
