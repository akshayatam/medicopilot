from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Action(str, Enum):
    LIST_TODAY_MEDICATIONS = "LIST_TODAY_MEDICATIONS"
    CHECK_DOSE_STATUS = "CHECK_DOSE_STATUS"
    FIND_NEXT_DOSE = "FIND_NEXT_DOSE"
    MARK_DOSE_TAKEN = "MARK_DOSE_TAKEN"
    GET_SAVED_INSTRUCTIONS = "GET_SAVED_INSTRUCTIONS"
    SHOW_MEDICATION_HISTORY = "SHOW_MEDICATION_HISTORY"
    CHECK_MISSED_DOSES = "CHECK_MISSED_DOSES"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    UNSAFE_MEDICAL_REQUEST = "UNSAFE_MEDICAL_REQUEST"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class Intent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Action
    medication_reference: str | None = None
    date_reference: str | None = None
    time_period: str | None = None
    # Routing confidence is optional model metadata. It never gates safety,
    # readiness, resolution, or tool execution.
    confidence: float | None = Field(default=None, ge=0, le=1, strict=True)
    clarification_question: str | None = None
    unsafe_reason: str | None = None

    @model_validator(mode="after")
    def normalize_action_fields(self) -> "Intent":
        """Remove irrelevant model chatter and reject unsafe contradictions."""
        complete_actions = {
            Action.FIND_NEXT_DOSE,
            Action.LIST_TODAY_MEDICATIONS,
            Action.SHOW_MEDICATION_HISTORY,
            Action.CHECK_MISSED_DOSES,
        }
        medication_specific = {
            Action.CHECK_DOSE_STATUS,
            Action.MARK_DOSE_TAKEN,
            Action.GET_SAVED_INSTRUCTIONS,
        }
        if self.action in complete_actions:
            self.clarification_question = None
            if self.action == Action.FIND_NEXT_DOSE:
                self.medication_reference = None
                self.time_period = None
            elif self.medication_reference:
                self.medication_reference = self.medication_reference.strip() or None
        elif self.action == Action.NEEDS_CLARIFICATION:
            if not self.clarification_question or not self.clarification_question.strip():
                raise ValueError("NEEDS_CLARIFICATION requires a non-empty clarification_question")
            self.clarification_question = self.clarification_question.strip()
        elif self.action in medication_specific:
            if self.medication_reference:
                self.medication_reference = self.medication_reference.strip() or None
                self.clarification_question = None
            elif self.clarification_question:
                # This commonly means the model discarded a vague phrase after deciding
                # it was ambiguous. Repair must restore the user's phrase instead.
                raise ValueError(
                    "Medication-specific actions must preserve any medication phrase "
                    "from the user; the deterministic resolver decides ambiguity"
                )
        return self
