from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from medication.models import (
    DoseLog,
    Medication,
    Patient,
    dose_logs_from_dict,
    medications_from_dict,
    patient_from_dict,
)


class MedicationRepository:
    def __init__(self, json_path: str | Path) -> None:
        self.json_path = Path(json_path)
        self._raw: dict[str, Any] = {}
        self.patient: Patient
        self.medications: list[Medication]
        self.dose_logs: list[DoseLog]
        self.reload()

    def reload(self) -> None:
        if not self.json_path.exists():
            raise FileNotFoundError(f"Patient data file not found: {self.json_path}")

        with self.json_path.open("r", encoding="utf-8") as file:
            self._raw = json.load(file)

        self.patient = patient_from_dict(self._raw)
        self.medications = medications_from_dict(self._raw)
        self.dose_logs = dose_logs_from_dict(self._raw)

    def save(self) -> None:
        self._raw["dose_logs"] = [
            {
                "id": log.id,
                "medication_id": log.medication_id,
                "scheduled_at": log.scheduled_at,
                "status": log.status,
                "taken_at": log.taken_at,
                "recorded_by": log.recorded_by,
                "source": log.source,
            }
            for log in self.dose_logs
        ]

        with self.json_path.open("w", encoding="utf-8") as file:
            json.dump(self._raw, file, indent=2, ensure_ascii=False)

    def get_medication_by_id(self, medication_id: str) -> Medication | None:
        return next(
            (med for med in self.medications if med.id == medication_id),
            None,
        )

    def find_medications(self, query: str) -> list[Medication]:
        normalized = query.casefold().strip()
        if not normalized:
            return []

        exact_matches = [
            med
            for med in self.medications
            if med.active
            and normalized
            in {
                    med.name.casefold(),
                    med.purpose_label.casefold(),
                    f"{med.name} {med.strength}".casefold(),
                    f"{med.purpose_label} medicine".casefold(),
                    f"{med.purpose_label} medication".casefold(),
                }
        ]
        if exact_matches:
            return exact_matches

        return [
            med
            for med in self.medications
            if med.active
            and (
                normalized in med.name.casefold()
                or normalized in med.purpose_label.casefold()
                or med.name.casefold() in normalized
                or med.purpose_label.casefold() in normalized
            )
        ]

    def find_medication(self, query: str) -> Medication | None:
        matches = self.find_medications(query)
        return matches[0] if len(matches) == 1 else None
