from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict

from medication.runtime_service import RuntimeMedicationService

PENDING_FOLLOWUP_TTL = timedelta(minutes=5)

AFFIRMATIVE = {"yes", "yeah", "yep", "i did", "yes i took it", "correct"}
NEGATIVE = {"no", "nope", "i did not", "not yet"}
CANCEL = {"cancel", "never mind", "nevermind", "stop"}


def classify_contextual_reply(text: str) -> Literal["affirmative", "negative", "cancel"] | None:
    normalized = " ".join(text.casefold().strip().replace(",", "").replace(".", "").split())
    if normalized in AFFIRMATIVE:
        return "affirmative"
    if normalized in NEGATIVE:
        return "negative"
    if normalized in CANCEL:
        return "cancel"
    return None


class PendingDoseFollowup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["record_missed_dose_as_taken"] = "record_missed_dose_as_taken"
    patient_id: str
    patient_data_version: str
    medication_id: str
    medication_display: str
    scheduled_at: datetime
    created_at: datetime
    expires_at: datetime
    prompt: str

    @classmethod
    def from_missed_dose(cls, patient_id: str, patient_data_version: str, dose: dict, now: datetime) -> "PendingDoseFollowup":
        scheduled = datetime.fromisoformat(dose["scheduled_at"])
        display = f"{dose['name']}{' ' + dose['strength'] if dose.get('strength') else ''}"
        prompt = f"Did you take {display} scheduled for {scheduled.strftime('%-I:%M %p')} on {scheduled.date().isoformat()}?"
        return cls(
            patient_id=patient_id, patient_data_version=patient_data_version,
            medication_id=dose["medication_id"], medication_display=display,
            scheduled_at=scheduled, created_at=now, expires_at=now + PENDING_FOLLOWUP_TTL, prompt=prompt,
        )


def handle_pending_reply(service: RuntimeMedicationService, pending: PendingDoseFollowup | None, reply: str) -> dict:
    kind = classify_contextual_reply(reply)
    if kind is None:
        raise ValueError("That response does not confirm or cancel the pending dose action.")
    if pending is None:
        return {"status": "no_pending_action", "message": "I’m not sure what you are confirming. Please tell me which medicine or action you mean."}
    if pending.patient_id != service.patient_id:
        raise ValueError("The pending confirmation belongs to another patient and was cancelled.")
    now = service.clock.now()
    if now < pending.created_at or now > pending.expires_at:
        raise ValueError("The pending dose confirmation expired. No dose record was changed.")
    if kind in {"negative", "cancel"}:
        return {"status": "cancelled", "message": "Okay. I did not change the dose record."}
    if pending.patient_data_version != service.patient_data_version():
        patient = service.repository.load()
        exact = [log for log in patient.dose_logs if log.medication_id == pending.medication_id and log.scheduled_at == pending.scheduled_at]
        if len(exact) == 1 and exact[0].status in {"taken", "taken_late"}:
            return service.mark_exact_dose_taken(pending.medication_id, pending.scheduled_at)
        raise ValueError("The patient data changed and the pending confirmation was cancelled. No dose record was changed.")
    return service.mark_exact_dose_taken(pending.medication_id, pending.scheduled_at)
