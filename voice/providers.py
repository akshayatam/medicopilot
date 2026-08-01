from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Protocol

import httpx

from voice.audio import inspect_wav
from voice.schemas import TranscriptionResult


class SpeechToTextProvider(Protocol):
    def transcribe(self, audio_path: Path, language: str | None = None) -> TranscriptionResult: ...


class GemmaAudioTranscriptionProvider:
    """Gemma audio through Ollama's verified WAV-in-images compatibility path."""

    name = "gemma4_audio"

    def __init__(self, base_url: str, model: str, timeout: float = 90) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def transcribe(self, audio_path: Path, language: str | None = None) -> TranscriptionResult:
        metadata = inspect_wav(audio_path)
        started = time.perf_counter()
        language_name = language or "the selected language"
        instruction = (
            f"Transcribe the following speech segment in {language_name} into {language_name} text.\n"
            "Output only the transcription. Do not add commentary or answer the spoken request. "
            "Write numbers as digits where appropriate and preserve medication names as closely as possible."
        )
        try:
            encoded = base64.b64encode(audio_path.read_bytes()).decode("ascii")
            response = httpx.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model, "stream": False, "think": False,
                    "messages": [{"role": "user", "content": instruction, "images": [encoded]}],
                    "options": {"temperature": 0, "num_ctx": 8192},
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            content = response.json().get("message", {}).get("content")
            text = content.strip() if isinstance(content, str) else ""
            if not text:
                return self._failure(metadata.duration_seconds, started, "The local model returned an empty transcription.", "empty_transcription", language)
            return TranscriptionResult(text=text, language=language, provider=self.name, duration_seconds=metadata.duration_seconds, processing_ms=(time.perf_counter() - started) * 1000, success=True)
        except httpx.TimeoutException:
            return self._failure(metadata.duration_seconds, started, "Local transcription timed out.", "timeout", language)
        except httpx.ConnectError:
            return self._failure(metadata.duration_seconds, started, "Ollama is not reachable.", "provider_unavailable", language)
        except (httpx.HTTPError, ValueError, TypeError):
            return self._failure(metadata.duration_seconds, started, "The local audio provider could not transcribe this recording.", "provider_error", language)

    def _failure(self, duration: float, started: float, warning: str, code: str, language: str | None) -> TranscriptionResult:
        return TranscriptionResult(language=language, provider=self.name, duration_seconds=duration, processing_ms=(time.perf_counter() - started) * 1000, success=False, warning=warning, error_code=code)
