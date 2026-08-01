from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class UserInput(BaseModel):
    text: str | None = None
    source: Literal["text", "voice", "image"] = "text"
    transcript: str | None = None
    image_path: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def text_only_for_now(self) -> "UserInput":
        if self.source != "text":
            raise ValueError("Only text input is currently supported")
        if not self.text or not self.text.strip():
            raise ValueError("Text input cannot be empty")
        return self


CurrentUseStatus = Literal["confirmed_current", "unverified", "historical", "discontinued", "conflicting"]
DoseStatus = Literal["upcoming", "due", "taken", "taken_late", "missed", "skipped_by_user", "unknown"]
DoseSource = Literal["app_event", "synthetic_adherence_simulation"]
AllergyStatus = Literal["not_recorded", "recorded", "no_known_allergies_explicitly_recorded"]


class MedicationAppearance(BaseModel):
    """Optional, verified presentation metadata; never a medication identifier."""

    description: str | None = None
    color: list[str] = Field(default_factory=list)
    shape: str | None = None
    dosage_form: str | None = None
    transparency: str | None = None
    size: str | None = None
    imprint: str | None = None
    special_features: list[str] = Field(default_factory=list)
    source: Literal[
        "synthetic_reconciliation_profile", "synthetic_demo_data", "patient_confirmed",
        "caregiver_confirmed", "pharmacist_confirmed", "prescription_label_confirmed",
    ] | None = None
    verification_status: Literal["verified", "unverified", "not_recorded"]
    verified_by: str | None = None
    verified_at: datetime | None = None

    @field_validator("description", "shape", "dosage_form", "transparency", "size", "imprint", "verified_by")
    @classmethod
    def nonempty_optional_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("appearance text fields cannot be empty")
        return value.strip() if value is not None else None

    @field_validator("color", "special_features")
    @classmethod
    def nonempty_list_text(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("appearance list values cannot be empty")
        return [value.strip() for value in values]

    @model_validator(mode="after")
    def verified_data_is_attributable(self) -> "MedicationAppearance":
        if self.verification_status == "verified":
            if not (self.description and self.source and self.verified_by and self.verified_at):
                raise ValueError("verified appearance requires description and complete provenance")
        if self.verification_status == "not_recorded" and any((
            self.description, self.color, self.shape, self.dosage_form, self.transparency,
            self.size, self.imprint, self.special_features,
        )):
            raise ValueError("not-recorded appearance cannot contain factual characteristics")
        return self


class ProvenancedSchedule(BaseModel):
    time: str
    period: str | None = None
    meal_context: str | None = None
    source: Literal["FHIR dosageInstruction.timing.repeat.timeOfDay", "synthetic_reconciliation_profile"]
    verified: bool
    verified_by: str | None = None
    verified_at: datetime | None = None

    @model_validator(mode="after")
    def verification_is_attributable(self) -> "ProvenancedSchedule":
        try:
            datetime.strptime(self.time, "%H:%M")
        except ValueError as exc:
            raise ValueError("schedule time must use HH:MM") from exc
        if not self.verified:
            raise ValueError("daily-plan schedules must be verified")
        if self.source == "synthetic_reconciliation_profile" and not (self.verified_by and self.verified_at):
            raise ValueError("synthetic schedules require verified_by and verified_at")
        return self


class MedicationPlanItem(BaseModel):
    id: str
    source_medication_request_ids: list[str] = Field(default_factory=list)
    patient_friendly_name: str
    aliases: list[str] = Field(default_factory=list)
    strength: str | None = None
    purpose_labels: list[str] = Field(default_factory=list)
    purpose_source: Literal["linked_fhir_reason", "verified_reconciliation", "not_recorded"] = "not_recorded"
    source_instruction: str | None = None
    appearance: MedicationAppearance | None = None
    schedule_type: Literal["scheduled", "as_needed", "unknown"] = "unknown"
    reminder_schedule: list[ProvenancedSchedule] = Field(default_factory=list)
    current_use_status: CurrentUseStatus = "unverified"
    included_in_daily_plan: bool = False
    reconciliation_status: Literal["needs_review", "verified"] = "needs_review"
    verified_by: str | None = None
    verified_at: datetime | None = None
    source: Literal["synthetic_reconciliation_profile", "explicit_reconciliation_record"]

    @model_validator(mode="after")
    def enforce_plan_rules(self) -> "MedicationPlanItem":
        if self.schedule_type == "as_needed" and self.reminder_schedule:
            raise ValueError("as-needed medication cannot have fixed reminders")
        if self.included_in_daily_plan:
            if self.current_use_status != "confirmed_current" or self.reconciliation_status != "verified":
                raise ValueError("daily-plan medication must be explicitly confirmed and verified")
            if self.schedule_type != "scheduled" or not self.reminder_schedule:
                raise ValueError("daily-plan medication requires a verified fixed schedule")
        if self.reconciliation_status == "verified" and not (self.verified_by and self.verified_at):
            raise ValueError("verified reconciliation requires verified_by and verified_at")
        return self


class ReconciliationDecision(BaseModel):
    medication_request_id: str
    current_use_status: CurrentUseStatus
    included_in_daily_plan: bool = False
    patient_friendly_name: str | None = None
    aliases: list[str] = Field(default_factory=list)
    purpose_labels: list[str] | None = None
    appearance: MedicationAppearance | None = None
    reminder_schedule: list[ProvenancedSchedule] = Field(default_factory=list)
    verified_by: str
    verified_at: datetime
    source: Literal["synthetic_reconciliation_profile", "explicit_reconciliation_record"]

    @model_validator(mode="after")
    def confirmed_only(self) -> "ReconciliationDecision":
        if self.included_in_daily_plan and self.current_use_status != "confirmed_current":
            raise ValueError("only confirmed-current medication can enter the daily plan")
        return self


class ReconciliationProfile(BaseModel):
    patient_id: str
    decisions: list[ReconciliationDecision]
    source: Literal["synthetic_reconciliation_profile", "explicit_reconciliation_record"]


class DoseLogRecord(BaseModel):
    id: str
    medication_id: str
    scheduled_at: datetime
    status: DoseStatus
    taken_at: datetime | None = None
    recorded_by: str | None = None
    source: DoseSource
    generation_parameters: dict[str, Any] | None = None

    @model_validator(mode="after")
    def status_matches_timestamp(self) -> "DoseLogRecord":
        taken = self.status in {"taken", "taken_late"}
        if taken and self.taken_at is None:
            raise ValueError("taken statuses require taken_at")
        if not taken and self.taken_at is not None:
            raise ValueError("non-taken statuses must not contain taken_at")
        if self.source == "synthetic_adherence_simulation" and self.generation_parameters is None:
            raise ValueError("simulated logs require generation_parameters")
        return self


class AllergyRecord(BaseModel):
    substance: str | None = None
    source: str
    details: dict[str, Any] = Field(default_factory=dict)


class AllergySection(BaseModel):
    allergy_status: AllergyStatus
    allergies: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def status_matches_list(self) -> "AllergySection":
        if self.allergy_status == "recorded" and not self.allergies:
            raise ValueError("recorded allergy status requires at least one allergy")
        if self.allergy_status != "recorded" and self.allergies:
            raise ValueError("empty-status allergy values cannot contain allergies")
        return self
