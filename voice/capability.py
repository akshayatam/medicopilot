from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx

from voice.audio import normalized_audio
from voice.providers import GemmaAudioTranscriptionProvider
from voice.schemas import VoiceCapabilityReport

PROBE_PHRASE = "the quick brown fox jumps over the lazy dog"


def probe_voice_capability(provider: GemmaAudioTranscriptionProvider) -> VoiceCapabilityReport:
    report = VoiceCapabilityReport(model_name=provider.model)
    try:
        version = httpx.get(f"{provider.base_url}/api/version", timeout=5)
        version.raise_for_status()
        report.ollama_reachable = True
        report.ollama_version = version.json().get("version")
        shown = httpx.post(f"{provider.base_url}/api/show", json={"model": provider.model}, timeout=10)
        if shown.status_code == 404:
            report.details.append("The configured model is not installed.")
            return report
        shown.raise_for_status()
        report.model_available = True
        capabilities = shown.json().get("capabilities", [])
        report.model_declares_audio = "audio" in capabilities
    except (httpx.HTTPError, ValueError, TypeError):
        report.details.append("Ollama could not be reached for the voice capability probe.")
        return report

    synthesizer = shutil.which("espeak-ng") or shutil.which("espeak")
    if not synthesizer:
        report.details.append("A harmless speech probe could not be generated because eSpeak is unavailable.")
        return report
    with tempfile.TemporaryDirectory(prefix="medicopilot-voice-probe-") as directory:
        source = Path(directory) / "probe-source.wav"
        completed = subprocess.run(
            [synthesizer, "-v", "en-us", "-s", "135", "-w", str(source), PROBE_PHRASE],
            capture_output=True, text=True, timeout=15, check=False,
        )
        if completed.returncode != 0:
            report.details.append("The harmless local speech probe could not be generated.")
            return report
        try:
            with normalized_audio(source) as (audio_path, _metadata):
                result = provider.transcribe(audio_path, "English")
        except ValueError as exc:
            report.details.append(str(exc))
            return report
    report.probe_processing_ms = result.processing_ms
    report.runtime_accepts_audio = result.success
    normalized = result.text.casefold().replace(".", "")
    anchors = {"quick", "fox", "lazy", "dog"}
    report.transcription_succeeded = result.success and len(anchors.intersection(normalized.split())) >= 3
    report.fallback_required = not report.transcription_succeeded
    if report.transcription_succeeded:
        report.details.append("A generated non-patient English speech sample was processed locally and content-verified.")
    else:
        report.details.append("The runtime response did not reliably reproduce the generated speech sample.")
    return report
