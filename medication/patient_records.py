from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PatientRecord:
    key: str
    display_name: str
    age: int | None
    gender: str
    path: Path

    @property
    def label(self) -> str:
        details = [value for value in (self.gender, f"age {self.age}" if self.age is not None else "") if value]
        return f"{self.display_name} ({', '.join(details)})" if details else self.display_name


class PatientRecordStore:
    """Read-only access to the converted synthetic patient records."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory).resolve()
        self._records = self._index_records()
        if not self._records:
            raise FileNotFoundError(f"No patient records found in: {self.directory}")

    def _index_records(self) -> list[PatientRecord]:
        if not self.directory.is_dir():
            return []

        records: list[PatientRecord] = []
        for path in sorted(self.directory.glob("*.medication-copilot.json")):
            try:
                with path.open("r", encoding="utf-8") as file:
                    data = json.load(file)
                patient = data.get("source_record", data)["patient"]
                age_value = patient.get("age_at_dataset_reference_date", patient.get("age"))
                records.append(
                    PatientRecord(
                        key=patient["id"],
                        display_name=patient["display_name"],
                        age=int(age_value) if age_value is not None else None,
                        gender=str(patient.get("gender", "")),
                        path=path.resolve(),
                    )
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return sorted(records, key=lambda item: (item.display_name.casefold(), item.key))

    def list_patients(self) -> list[PatientRecord]:
        return list(self._records)

    def load(self, key: str) -> dict[str, Any]:
        record = next((item for item in self._records if item.key == key), None)
        if record is None:
            raise ValueError("Please select a valid patient.")
        with record.path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def overview(self, key: str) -> dict[str, Any]:
        data = self.load(key)
        source = data.get("source_record", data)
        patient = source["patient"]
        conditions = source.get("conditions", {})
        active_conditions = conditions.get("clinical_conditions", [])
        medications = [item for item in data.get("medication_plan", {}).get("medications", []) if item.get("included_in_daily_plan")]
        if "medication_plan" not in data:  # legacy, explicitly synthetic demo records
            medications = [item for item in data.get("medications", []) if item.get("active", True)]
        allergies = source.get("allergies", [])
        return {
            "name": patient.get("display_name"),
            "patient_id": patient.get("id"),
            "birth_date": patient.get("birth_date"),
            "age": patient.get("age_at_dataset_reference_date", patient.get("age")),
            "gender": patient.get("gender"),
            "preferred_language": patient.get("preferred_language"),
            "active_conditions": len(active_conditions),
            "active_medications": len(medications),
            "allergies": len(allergies),
            "allergy_status": source.get("allergy_status", "not_recorded"),
            "ready_for_medication_tracking": data.get("import_summary", {}).get("ready_for_medication_tracking", False),
        }

    def llm_context(self, key: str) -> str:
        data = self.load(key)
        source = data.get("source_record", data)
        patient = source.get("patient", {})
        planned = data.get("medication_plan", {}).get("medications", [])
        confirmed = [
            {
                "id": med.get("id"), "name": med.get("patient_friendly_name"),
                "strength": med.get("strength"), "aliases": med.get("aliases", []),
                "purpose_labels": med.get("purpose_labels", []),
            }
            for med in planned
            if med.get("current_use_status") == "confirmed_current" and med.get("included_in_daily_plan")
        ]
        schedules = [
            {"medication_id": med.get("id"), "reminder_schedule": med.get("reminder_schedule", [])}
            for med in planned if med.get("included_in_daily_plan")
        ]
        grounded_record = {
            "patient": {"preferred_language": patient.get("preferred_language"), "timezone": patient.get("timezone")},
            "confirmed_medications": confirmed,
            "verified_schedules": schedules,
            "recent_dose_logs": data.get("dose_logs", [])[-30:],
            "allergy_status": source.get("allergy_status", "not_recorded"),
            "allergies": source.get("allergies", []),
            "clinical_conditions": [
                condition for condition in source.get("conditions", {}).get("clinical_conditions", [])
                if condition.get("visibility", {}).get("include_in_medication_context", True)
            ],
        }
        return json.dumps(grounded_record, ensure_ascii=False, separators=(",", ":"))
