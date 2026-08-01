from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Settings:
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "gemma4:e2b")
    ollama_timeout_seconds: float = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "45"))
    demo_now: str | None = os.getenv("DEMO_NOW")
    dose_due_window_minutes: int = int(os.getenv("DOSE_DUE_WINDOW_MINUTES", "15"))
    dose_missed_after_minutes: int = int(os.getenv("DOSE_MISSED_AFTER_MINUTES", "30"))
    data_file: Path = ROOT / "data" / "synthetic_patient.json"
    runtime_patients_directory: Path = ROOT / "data" / "runtime_patients"

    def __post_init__(self) -> None:
        if self.dose_due_window_minutes < 0 or self.dose_missed_after_minutes < 0:
            raise ValueError("dose status policy minutes must be non-negative")
        if self.dose_missed_after_minutes < self.dose_due_window_minutes:
            raise ValueError("DOSE_MISSED_AFTER_MINUTES must be at least DOSE_DUE_WINDOW_MINUTES")
        if self.demo_now:
            parsed = datetime.fromisoformat(self.demo_now)
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError("DEMO_NOW must be an ISO-8601 timestamp with a timezone offset")


settings = Settings()
