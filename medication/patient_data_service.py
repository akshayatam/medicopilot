from __future__ import annotations

import json
from pathlib import Path
from threading import RLock
from typing import Any

from pydantic import ValidationError

from medication.runtime import PatientSummary, ReadinessResult, RuntimePatient


class PatientDataError(ValueError):
    pass


class PatientDataService:
    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory).resolve()
        self._lock = RLock()
        self._paths: dict[str, Path] = {}
        self._patients: dict[str, RuntimePatient] = {}
        self.validation_errors: dict[str, str] = {}
        self.refresh()

    def refresh(self) -> None:
        with self._lock:
            self._paths.clear(); self._patients.clear(); self.validation_errors.clear()
            if not self.directory.is_dir():
                return
            for path in sorted(self.directory.glob("*.runtime.json")):
                try:
                    patient = self._load_path(path)
                    if patient.source_record.patient.id in self._paths:
                        raise PatientDataError("duplicate patient id")
                    self._paths[patient.source_record.patient.id] = path
                    self._patients[patient.source_record.patient.id] = patient
                except (OSError, json.JSONDecodeError, ValidationError, PatientDataError) as exc:
                    self.validation_errors[path.name] = str(exc)

    @staticmethod
    def _load_path(path: Path) -> RuntimePatient:
        with path.open("r", encoding="utf-8") as handle:
            data: Any = json.load(handle)
        if not isinstance(data, dict):
            raise PatientDataError("runtime patient file must contain a JSON object")
        version = data.get("schema_version")
        if version != "2.0":
            raise PatientDataError(f"Unsupported patient schema version {version!r}; expected '2.0'.")
        return RuntimePatient.model_validate(data)

    def list_available_patients(self) -> list[PatientSummary]:
        return sorted([
            PatientSummary(patient_id=p.source_record.patient.id, display_name=p.source_record.patient.display_name,
                           age=p.source_record.patient.age_at_dataset_reference_date,
                           preferred_language=p.source_record.patient.preferred_language,
                           timezone=p.source_record.patient.timezone,
                           ready=p.import_summary.ready_for_medication_tracking, path=self._paths[p.source_record.patient.id])
            for p in self._patients.values()
        ], key=lambda p: (p.display_name.casefold(), p.patient_id))

    def load_patient(self, patient_id: str) -> RuntimePatient:
        patient = self._patients.get(patient_id)
        if patient is None:
            raise PatientDataError("Please select a valid runtime patient.")
        return patient.model_copy(deep=True)

    def get_readiness(self, patient_id: str) -> ReadinessResult:
        return self.load_patient(patient_id).import_summary

    def reload_patient(self, patient_id: str) -> RuntimePatient:
        path = self._paths.get(patient_id)
        if path is None:
            raise PatientDataError("Please select a valid runtime patient.")
        with self._lock:
            patient = self._load_path(path)
            self._patients[patient_id] = patient
            return patient.model_copy(deep=True)

    def save_patient(self, patient: RuntimePatient) -> None:
        patient = RuntimePatient.model_validate(patient)
        patient_id = patient.source_record.patient.id
        path = self._paths.get(patient_id)
        if path is None:
            raise PatientDataError("Cannot save an unknown runtime patient.")
        temporary = path.with_suffix(path.suffix + ".tmp")
        with self._lock:
            temporary.write_text(patient.model_dump_json(indent=2) + "\n", encoding="utf-8")
            temporary.replace(path)
            self._patients[patient_id] = patient.model_copy(deep=True)

