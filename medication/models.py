from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Patient:
    id: str
    display_name: str
    age: int
    preferred_language: str
    timezone: str


@dataclass(frozen=True)
class Medication:
    id: str
    name: str
    strength: str
    purpose_label: str
    schedule: list[dict[str, str]]
    instructions: str
    source: str
    active: bool


@dataclass
class DoseLog:
    id: str
    medication_id: str
    scheduled_at: str
    status: str
    taken_at: str | None
    recorded_by: str | None
    source: str = "app_event"


def patient_from_dict(data: dict[str, Any]) -> Patient:
    patient = data["patient"]
    return Patient(
        id=patient["id"],
        display_name=patient["display_name"],
        age=int(patient["age"]),
        preferred_language=patient["preferred_language"],
        timezone=patient["timezone"],
    )


def medications_from_dict(data: dict[str, Any]) -> list[Medication]:
    return [
        Medication(
            id=item["id"],
            name=item["name"],
            strength=item["strength"],
            purpose_label=item["purpose_label"],
            schedule=item["schedule"],
            instructions=item["instructions"],
            source=item["source"],
            active=bool(item["active"]),
        )
        for item in data["medications"]
    ]


def dose_logs_from_dict(data: dict[str, Any]) -> list[DoseLog]:
    return [
        DoseLog(
            id=item["id"],
            medication_id=item["medication_id"],
            scheduled_at=item["scheduled_at"],
            status=item["status"],
            taken_at=item.get("taken_at"),
            recorded_by=item.get("recorded_by"),
            source=item.get("source", "app_event"),
        )
        for item in data["dose_logs"]
    ]
