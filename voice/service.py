from __future__ import annotations

from datetime import timedelta

from gemma.orchestrator import MedicationOrchestrator
from gemma.schemas import Action, Intent
from medication.resolver import ResolutionStatus
from medication.runtime_service import RuntimeMedicationService
from medication.safety import check_safety
from medication.schemas import UserInput
from voice.schemas import PendingVoiceAction

PENDING_ACTION_TTL = timedelta(minutes=5)


class _FixedRouter:
    def __init__(self, intent: Intent, client) -> None:
        self.intent = intent; self.client = client
        self.raw_model_json = None; self.repair_model_json = None; self.repair_used = False

    def route(self, _text: str) -> Intent:
        return self.intent


class VoiceInteractionService:
    def __init__(self, medication_service: RuntimeMedicationService, router) -> None:
        self.medication_service = medication_service
        self.router = router

    def submit_transcript(self, transcript: str):
        text = " ".join((transcript or "").strip().split())
        if not text:
            raise ValueError("Review and submit a non-empty transcript.")
        safety = check_safety(text)
        if safety.unsafe:
            return MedicationOrchestrator(self.medication_service, self.router).handle(UserInput(text=text)), None
        intent = self.router.route(text)
        if intent.action != Action.MARK_DOSE_TAKEN:
            result = MedicationOrchestrator(self.medication_service, _FixedRouter(intent, self.router.client)).handle(UserInput(text=text))
            return result, None
        self.medication_service.ensure_ready()
        if not intent.medication_reference:
            raise ValueError("Which saved medication do you mean? Please provide its name or purpose.")
        resolution = self.medication_service.resolve(intent.medication_reference)
        if resolution.status == ResolutionStatus.NOT_FOUND:
            raise ValueError(f"No confirmed medication matches '{intent.medication_reference}'.")
        if resolution.status == ResolutionStatus.AMBIGUOUS:
            names = ", ".join(match.display_name for match in resolution.matches)
            raise ValueError(f"Which confirmed medication do you mean? Matches: {names}")
        match = resolution.matches[0]
        patient = self.medication_service.repository.load()
        today = self.medication_service.clock.now().date()
        candidates = [log for log in patient.dose_logs if log.medication_id == match.medication_id and log.scheduled_at.date() == today]
        if not candidates:
            raise ValueError("No scheduled dose was found for that confirmed medication today.")
        dose = min(candidates, key=lambda log: abs((log.scheduled_at - self.medication_service.clock.now()).total_seconds()))
        pending = PendingVoiceAction(
            patient_id=self.medication_service.patient_id, action="MARK_DOSE_TAKEN",
            medication_id=match.medication_id, medication_reference=intent.medication_reference,
            medication_display=match.display_name, scheduled_at=dose.scheduled_at,
            appearance=self.medication_service._verified_appearance(
                next(med for med in self.medication_service.repository.get_reconciled_medications() if med.id == match.medication_id)
            ),
            created_at=self.medication_service.clock.now(), transcript=text,
        )
        return None, pending

    def confirm(self, pending: PendingVoiceAction):
        now = self.medication_service.clock.now()
        if pending.patient_id != self.medication_service.patient_id:
            raise ValueError("The pending voice action belongs to another patient and was cancelled.")
        if pending.created_at > now or now - pending.created_at > PENDING_ACTION_TTL:
            raise ValueError("The pending voice confirmation expired. Please submit the transcript again.")
        if check_safety(pending.transcript).unsafe:
            raise ValueError("The request cannot be recorded because it requires medication advice or emergency help.")
        self.medication_service.ensure_ready()
        resolution = self.medication_service.resolve(pending.medication_reference)
        if resolution.status != ResolutionStatus.MATCHED or resolution.matches[0].medication_id != pending.medication_id:
            raise ValueError("The saved medication no longer matches the pending voice action.")
        patient = self.medication_service.repository.load()
        exact = [log for log in patient.dose_logs if log.medication_id == pending.medication_id and log.scheduled_at == pending.scheduled_at]
        if len(exact) != 1:
            raise ValueError("The exact scheduled dose could not be revalidated.")
        return self.medication_service.mark_exact_dose_taken(pending.medication_id, pending.scheduled_at)
