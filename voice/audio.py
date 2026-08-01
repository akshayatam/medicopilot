from __future__ import annotations

import shutil
import subprocess
import tempfile
import wave
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from voice.schemas import AudioMetadata

MAX_AUDIO_SECONDS = 30
MAX_AUDIO_BYTES = 10 * 1024 * 1024


class AudioValidationError(ValueError):
    pass


def inspect_wav(path: Path) -> AudioMetadata:
    if not path.is_file():
        raise AudioValidationError("No audio recording was provided.")
    size = path.stat().st_size
    if size <= 44:
        raise AudioValidationError("The audio recording is empty.")
    if size > MAX_AUDIO_BYTES:
        raise AudioValidationError("The audio recording is too large.")
    try:
        with wave.open(str(path), "rb") as source:
            frames = source.getnframes()
            rate = source.getframerate()
            channels = source.getnchannels()
            width = source.getsampwidth()
    except (wave.Error, EOFError, OSError) as exc:
        raise AudioValidationError("The audio recording could not be decoded.") from exc
    duration = frames / rate if rate else 0
    if duration <= 0:
        raise AudioValidationError("The audio recording is empty.")
    if duration > MAX_AUDIO_SECONDS:
        raise AudioValidationError("The recording is longer than the 30-second limit.")
    return AudioMetadata(duration_seconds=duration, size_bytes=size, sample_rate_hz=rate, channels=channels, sample_width_bytes=width)


@contextmanager
def normalized_audio(source: str | Path) -> Iterator[tuple[Path, AudioMetadata]]:
    source_path = Path(source)
    if not source_path.is_file():
        raise AudioValidationError("No audio recording was provided.")
    if source_path.stat().st_size > MAX_AUDIO_BYTES:
        raise AudioValidationError("The audio recording is too large.")
    temp_dir = Path(tempfile.mkdtemp(prefix="medicopilot-voice-"))
    target = temp_dir / "audio.wav"
    try:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            if source_path.suffix.casefold() != ".wav":
                raise AudioValidationError("Local audio conversion is unavailable. Please upload a WAV file.")
            shutil.copyfile(source_path, target)
        else:
            completed = subprocess.run(
                [ffmpeg, "-y", "-loglevel", "error", "-i", str(source_path), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(target)],
                capture_output=True, text=True, timeout=20, check=False,
            )
            if completed.returncode != 0:
                raise AudioValidationError("The audio recording could not be converted locally.")
        yield target, inspect_wav(target)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
