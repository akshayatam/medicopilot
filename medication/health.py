from __future__ import annotations

from datetime import datetime
from typing import Any

from gemma.client import OllamaClient
from medication.patient_data_service import PatientDataService


class ApplicationHealthService:
    def __init__(self, client: OllamaClient, patients: PatientDataService, demo_now: str | None = None) -> None:
        self.client = client; self.patients = patients; self.demo_now = demo_now

    def check(self) -> dict[str, Any]:
        model = self.client.health_check()
        summaries = self.patients.list_available_patients()
        return {
            "ollama_reachable": bool(model.get("reachable")),
            "configured_model": self.client.model,
            "model_available": bool(model.get("model_available")),
            "generation_ok": bool(model.get("generation_ok")),
            "patient_directory_readable": self.patients.directory.is_dir(),
            "patients_loaded": len(summaries),
            "patients_ready": sum(p.ready for p in summaries),
            "schema_validation_ok": not self.patients.validation_errors and bool(summaries),
            "timezone_data_valid": bool(summaries) and not self.patients.validation_errors,
            "schema_errors": self.patients.validation_errors,
            "healthy_for_deterministic_use": bool(summaries) and not self.patients.validation_errors and any(p.ready for p in summaries),
            "active_application_time": datetime.fromisoformat(self.demo_now).isoformat() if self.demo_now else "system_clock_per_patient_timezone",
        }
