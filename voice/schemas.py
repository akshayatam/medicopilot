from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AudioMetadata(BaseModel):
    duration_seconds: float = Field(gt=0, le=30)
    size_bytes: int = Field(gt=0)
    sample_rate_hz: int = Field(gt=0)
    channels: int = Field(gt=0)
    sample_width_bytes: int = Field(gt=0)


class TranscriptionResult(BaseModel):
    text: str = ""
    language: str | None = None
    provider: str
    duration_seconds: float
    processing_ms: float | None = None
    success: bool
    warning: str | None = None
    error_code: str | None = None


class VoiceCapabilityReport(BaseModel):
    ollama_reachable: bool = False
    ollama_version: str | None = None
    model_available: bool = False
    model_name: str
    model_declares_audio: bool = False
    runtime_accepts_audio: bool = False
    transcription_succeeded: bool = False
    audio_limit_seconds: int = 30
    fallback_required: bool = True
    provider: str = "gemma4_audio"
    api_transport: str = "ollama_chat_images_compatibility"
    probe_processing_ms: float | None = None
    details: list[str] = Field(default_factory=list)


class PendingVoiceAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    patient_id: str
    action: Literal["MARK_DOSE_TAKEN"]
    medication_id: str
    medication_reference: str
    medication_display: str
    appearance: str | None = None
    scheduled_at: datetime
    created_at: datetime
    transcript: str
    confirmation_required: bool = True
