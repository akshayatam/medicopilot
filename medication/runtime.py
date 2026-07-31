from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator

from medication.schemas import DoseLogRecord, MedicationPlanItem

SUPPORTED_SCHEMA_VERSIONS = {"2.0"}


class RuntimePatientProfile(BaseModel):
    id: str
    display_name: str
    birth_date: str
    age_at_dataset_reference_date: int = Field(ge=60)
    gender: str | None = None
    preferred_language: str | None = None
    timezone: str

    @model_validator(mode="after")
    def valid_timezone(self) -> "RuntimePatientProfile":
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("patient timezone must be a valid IANA timezone") from exc
        return self


class SourceRecord(BaseModel):
    model_config = ConfigDict(extra="allow")
    patient: RuntimePatientProfile
    conditions: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    allergies: list[dict[str, Any]] = Field(default_factory=list)
    allergy_status: Literal["not_recorded", "recorded", "no_known_allergies_explicitly_recorded"]
    medications: list[dict[str, Any]] = Field(default_factory=list)
    clinical_administrations: list[dict[str, Any]] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)


class RuntimeMedicationPlan(BaseModel):
    patient_id: str
    status: Literal["verified", "needs_review"]
    medications: list[MedicationPlanItem] = Field(default_factory=list)
    source: str


class ReadinessResult(BaseModel):
    ready_for_medication_tracking: bool
    blocking_issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source: str = "deterministic_readiness_validation"


class RuntimePatient(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str
    source_record: SourceRecord
    medication_plan: RuntimeMedicationPlan
    dose_logs: list[DoseLogRecord] = Field(default_factory=list)
    import_summary: ReadinessResult
    support_profile: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def boundaries_are_consistent(self) -> "RuntimePatient":
        if self.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(f"unsupported schema_version: {self.schema_version}")
        if self.medication_plan.patient_id != self.source_record.patient.id:
            raise ValueError("medication plan patient_id does not match patient")
        plan_ids = {m.id for m in self.medication_plan.medications}
        if any(log.medication_id not in plan_ids for log in self.dose_logs):
            raise ValueError("dose log references medication outside verified plan")
        keys = [(log.medication_id, log.scheduled_at.isoformat()) for log in self.dose_logs]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate scheduled dose instances are not allowed")
        if self.import_summary.ready_for_medication_tracking:
            if self.medication_plan.status != "verified":
                raise ValueError("ready patient requires verified medication plan")
            included = [m for m in self.medication_plan.medications if m.included_in_daily_plan]
            if not included:
                raise ValueError("ready patient requires confirmed daily medication")
        return self


class PatientSummary(BaseModel):
    patient_id: str
    display_name: str
    age: int
    preferred_language: str | None
    timezone: str
    ready: bool
    path: Path

    @property
    def label(self) -> str:
        state = "Ready" if self.ready else "Needs review"
        return f"{self.display_name} — {self.age} — {state}"

