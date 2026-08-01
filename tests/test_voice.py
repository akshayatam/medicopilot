from __future__ import annotations

import json
import shutil
import struct
import wave
from pathlib import Path

import httpx
import pytest

from gemma.schemas import Action, Intent
from medication.clock import FixedClock
from medication.patient_data_service import PatientDataService
from medication.runtime_service import RuntimeMedicationService
from voice.audio import AudioValidationError, inspect_wav, normalized_audio
from voice.providers import GemmaAudioTranscriptionProvider
from voice.schemas import PendingVoiceAction
from voice.schemas import TranscriptionResult
from voice.service import VoiceInteractionService


def make_wav(path: Path, seconds: float = 1, rate: int = 16000) -> Path:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1); output.setsampwidth(2); output.setframerate(rate)
        output.writeframes(b"".join(struct.pack("<h", 1000 if index % 20 < 10 else -1000) for index in range(int(seconds * rate))))
    return path


def runtime_patients(tmp_path: Path) -> PatientDataService:
    target = tmp_path / "patients"
    shutil.copytree(Path(__file__).parents[1] / "data" / "runtime_patients", target)
    return PatientDataService(target)


class StubClient:
    last_latency_ms = 1


class StubRouter:
    client = StubClient()
    def __init__(self, intent: Intent): self.intent = intent
    def route(self, _text: str) -> Intent: return self.intent


def test_audio_validation_and_limit(tmp_path):
    valid = make_wav(tmp_path / "valid.wav")
    assert inspect_wav(valid).duration_seconds == 1
    with pytest.raises(AudioValidationError, match="provided"):
        inspect_wav(tmp_path / "missing.wav")
    corrupt = tmp_path / "corrupt.wav"; corrupt.write_bytes(b"not audio")
    with pytest.raises(AudioValidationError, match="empty|decoded"):
        inspect_wav(corrupt)
    with pytest.raises(AudioValidationError, match="30-second"):
        inspect_wav(make_wav(tmp_path / "long.wav", 30.1))


def test_normalized_temporary_audio_is_deleted(tmp_path):
    source = make_wav(tmp_path / "source.wav")
    with normalized_audio(source) as (temporary, metadata):
        parent = temporary.parent
        assert temporary.exists() and metadata.sample_rate_hz == 16000
        assert "medicopilot-voice-" in parent.name
    assert not parent.exists()


def test_provider_sends_audio_only_to_ollama_and_disables_thinking(tmp_path, monkeypatch):
    audio = make_wav(tmp_path / "speech.wav")
    captured = {}
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"message": {"content": "I took my vitamin D."}}
    def post(_url, **kwargs):
        captured.update(kwargs["json"]); return Response()
    monkeypatch.setattr(httpx, "post", post)
    result = GemmaAudioTranscriptionProvider("http://local", "gemma4:e2b").transcribe(audio, "English")
    assert result.success and result.text == "I took my vitamin D."
    assert captured["think"] is False and "images" in captured["messages"][0]
    serialized = json.dumps(captured)
    assert "patient_id" not in serialized and "source_record" not in serialized
    assert "appearance" not in serialized and "pale-yellow" not in serialized


def test_provider_failure_is_safe(tmp_path, monkeypatch):
    audio = make_wav(tmp_path / "speech.wav")
    monkeypatch.setattr(httpx, "post", lambda *_a, **_k: (_ for _ in ()).throw(httpx.ConnectError("offline")))
    result = GemmaAudioTranscriptionProvider("http://local", "model").transcribe(audio)
    assert not result.success and result.error_code == "provider_unavailable" and not result.text


def test_voice_mutation_waits_for_confirmation_and_executes_once(tmp_path):
    patients = runtime_patients(tmp_path)
    service = RuntimeMedicationService(patients, "demo-ready-001", FixedClock("2026-08-01T10:00:00-04:00"))
    interaction = VoiceInteractionService(service, StubRouter(Intent(action=Action.MARK_DOSE_TAKEN, medication_reference="lunch tablet")))
    before = patients.load_patient("demo-ready-001").model_dump_json()
    result, pending = interaction.submit_transcript("I took my lunch tablet")
    assert result is None and pending and pending.medication_display == "Vitamin D3 1000 IU"
    assert pending.appearance == "Small, pale-yellow softgel capsule."
    assert patients.reload_patient("demo-ready-001").model_dump_json() == before
    first = interaction.confirm(pending); second = interaction.confirm(pending)
    assert first["status"] == "taken" and second["status"] == "already_taken"
    persisted = next((tmp_path / "patients").glob("ready.runtime.json")).read_text()
    assert "I took my lunch tablet" not in persisted
    assert "pending_voice_action" not in persisted and "base64" not in persisted


def test_ambiguous_unready_expired_and_patient_mismatch_never_mutate(tmp_path):
    patients = runtime_patients(tmp_path)
    ready = RuntimeMedicationService(patients, "demo-ready-001", FixedClock("2026-08-01T10:00:00-04:00"))
    before = patients.load_patient("demo-ready-001").model_dump_json()
    with pytest.raises(ValueError, match="Which confirmed"):
        VoiceInteractionService(ready, StubRouter(Intent(action=Action.MARK_DOSE_TAKEN, medication_reference="tablet"))).submit_transcript("Mark my tablet")
    unready = RuntimeMedicationService(patients, "demo-unready-001", FixedClock("2026-08-01T10:00:00-04:00"))
    with pytest.raises(ValueError, match="not been verified"):
        VoiceInteractionService(unready, StubRouter(Intent(action=Action.MARK_DOSE_TAKEN, medication_reference="tablet"))).submit_transcript("Mark my tablet")
    _, pending = VoiceInteractionService(ready, StubRouter(Intent(action=Action.MARK_DOSE_TAKEN, medication_reference="lunch tablet"))).submit_transcript("I took lunch tablet")
    expired = pending.model_copy(update={"created_at": pending.created_at.replace(hour=9, minute=50)})
    with pytest.raises(ValueError, match="expired"):
        VoiceInteractionService(ready, StubRouter(Intent(action=Action.MARK_DOSE_TAKEN, medication_reference="lunch tablet"))).confirm(expired)
    other = PendingVoiceAction.model_validate(pending.model_dump() | {"patient_id": "another"})
    with pytest.raises(ValueError, match="another patient"):
        VoiceInteractionService(ready, StubRouter(Intent(action=Action.MARK_DOSE_TAKEN))).confirm(other)
    assert patients.reload_patient("demo-ready-001").model_dump_json() == before


def test_unsafe_voice_bypasses_router_and_read_only_uses_orchestrator(tmp_path):
    patients = runtime_patients(tmp_path)
    service = RuntimeMedicationService(patients, "demo-ready-001", FixedClock("2026-08-01T10:00:00-04:00"))
    class ExplodingRouter(StubRouter):
        def route(self, _text): raise AssertionError("unsafe voice must bypass routing")
    unsafe, pending = VoiceInteractionService(service, ExplodingRouter(Intent(action=Action.FIND_NEXT_DOSE))).submit_transcript("Should I double my dose?")
    assert unsafe.outcome == "unsafe_request" and pending is None
    readonly, pending = VoiceInteractionService(service, StubRouter(Intent(action=Action.FIND_NEXT_DOSE))).submit_transcript("What comes next?")
    assert "Vitamin D3" in readonly.response and pending is None


def test_voice_session_fields_are_isolated():
    from ui.gradio_app import new_session_state
    first = new_session_state("a"); second = new_session_state("b")
    first["voice_transcript"] = "private session text"
    first["pending_voice_action"] = {"x": 1}
    assert second["voice_transcript"] == "" and second["pending_voice_action"] is None


def test_capability_probe_requires_content_match_not_http_success(tmp_path, monkeypatch):
    from contextlib import contextmanager
    import voice.capability as capability
    audio = make_wav(tmp_path / "probe.wav")
    class Response:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"version": "test"}
    class ShowResponse(Response):
        def json(self): return {"capabilities": ["audio"]}
    monkeypatch.setattr(httpx, "get", lambda *_a, **_k: Response())
    monkeypatch.setattr(httpx, "post", lambda *_a, **_k: ShowResponse())
    monkeypatch.setattr(capability.shutil, "which", lambda _name: "/usr/bin/espeak")
    monkeypatch.setattr(capability.subprocess, "run", lambda *_a, **_k: type("Completed", (), {"returncode": 0})())
    @contextmanager
    def fake_normalized(_source): yield audio, inspect_wav(audio)
    monkeypatch.setattr(capability, "normalized_audio", fake_normalized)
    provider = GemmaAudioTranscriptionProvider("http://local", "gemma4:e2b")
    monkeypatch.setattr(provider, "transcribe", lambda *_a, **_k: TranscriptionResult(text="transcription", language="English", provider="fake", duration_seconds=1, success=True))
    report = capability.probe_voice_capability(provider)
    assert report.model_declares_audio and report.runtime_accepts_audio
    assert not report.transcription_succeeded and report.fallback_required
