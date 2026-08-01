"""Local, ephemeral voice-input support."""

from voice.providers import GemmaAudioTranscriptionProvider, SpeechToTextProvider
from voice.schemas import TranscriptionResult, VoiceCapabilityReport

__all__ = [
    "GemmaAudioTranscriptionProvider",
    "SpeechToTextProvider",
    "TranscriptionResult",
    "VoiceCapabilityReport",
]
