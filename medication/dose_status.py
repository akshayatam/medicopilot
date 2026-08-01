from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from medication.schemas import DoseLogRecord, DoseStatus


class DoseStatusPolicy(BaseModel):
    """Non-clinical application policy for time-derived dose presentation."""

    due_window_minutes: int = Field(default=15, ge=0)
    missed_after_minutes: int = Field(default=30, ge=0)

    @model_validator(mode="after")
    def missed_threshold_follows_due_window(self) -> "DoseStatusPolicy":
        if self.missed_after_minutes < self.due_window_minutes:
            raise ValueError("missed-after threshold must be at least the due window")
        return self


def calculate_effective_dose_status(
    dose: DoseLogRecord,
    now: datetime,
    policy: DoseStatusPolicy,
) -> DoseStatus:
    """Return one canonical query-time status without mutating the dose ledger."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("effective dose status requires a timezone-aware current time")
    if dose.scheduled_at.tzinfo is None or dose.scheduled_at.utcoffset() is None:
        raise ValueError("effective dose status requires a timezone-aware scheduled time")
    if dose.taken_at is not None and (dose.taken_at.tzinfo is None or dose.taken_at.utcoffset() is None):
        raise ValueError("effective dose status requires a timezone-aware taken time")

    if dose.status == "taken_late":
        return "taken_late"
    if dose.status == "taken":
        late_after = dose.scheduled_at + timedelta(minutes=policy.due_window_minutes)
        return "taken_late" if dose.taken_at and dose.taken_at > late_after else "taken"
    if dose.status in {"skipped_by_user", "unknown", "missed"}:
        return dose.status
    if now < dose.scheduled_at:
        return "upcoming"
    if now <= dose.scheduled_at + timedelta(minutes=policy.missed_after_minutes):
        return "due"
    return "missed"


class MissedDoseItem(BaseModel):
    medication_id: str
    name: str
    strength: str = ""
    scheduled_at: datetime
    stored_status: DoseStatus
    effective_status: Literal["missed"] = "missed"
    recorded_taken: Literal[False] = False


class MissedDoseResult(BaseModel):
    status: Literal["no_missed_doses", "missed_doses_found", "no_schedule_data"]
    date: str
    doses: list[MissedDoseItem] = Field(default_factory=list)
    message: str
    dose_status_policy: DoseStatusPolicy
