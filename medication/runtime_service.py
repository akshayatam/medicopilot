from __future__ import annotations

from datetime import datetime

from medication.clock import Clock
from medication.patient_data_service import PatientDataService
from medication.resolver import MedicationResolution, MedicationResolver, ResolutionStatus
from medication.runtime_repository import RuntimeMedicationRepository

UNREADY_MESSAGE = "The medication plan has not been verified yet. Complete medication review before using reminders or dose tracking."


class RuntimeMedicationService:
    def __init__(self, patients: PatientDataService, patient_id: str, clock: Clock) -> None:
        self.patients = patients; self.patient_id = patient_id; self.clock = clock
        self.repository = RuntimeMedicationRepository(patients, patient_id)
        self.resolver = MedicationResolver()

    def ensure_ready(self) -> None:
        if not self.patients.get_readiness(self.patient_id).ready_for_medication_tracking:
            raise ValueError(UNREADY_MESSAGE)

    def resolve(self, query: str) -> MedicationResolution:
        return self.resolver.resolve(query, self.repository.get_reconciled_medications())

    def _med(self, reference: str):
        resolution = self.resolve(reference)
        if resolution.status == ResolutionStatus.NOT_FOUND: raise ValueError(f"No confirmed medication matches '{reference}'.")
        if resolution.status == ResolutionStatus.AMBIGUOUS:
            names = ", ".join(m.display_name for m in resolution.matches)
            raise ValueError(f"Which confirmed medication do you mean? Matches: {names}")
        med_id = resolution.matches[0].medication_id
        return next(m for m in self.repository.get_reconciled_medications() if m.id == med_id)

    def list_today_medications(self, *_):
        self.ensure_ready(); patient = self.repository.load(); today = self.clock.now().date()
        meds = {m.id: m for m in self.repository.get_confirmed_medications()}
        results = [{"dose_id": l.id, "name": meds[l.medication_id].patient_friendly_name, "strength": meds[l.medication_id].strength or "", "scheduled_at": l.scheduled_at.isoformat(), "status": l.status, "taken_at": l.taken_at.isoformat() if l.taken_at else ""} for l in patient.dose_logs if l.medication_id in meds and l.scheduled_at.date() == today]
        if not results:
            return {"status": "no_data", "date": today.isoformat(), "message": f"No dose instances are stored for {today.isoformat()}. No other date was substituted."}
        return results

    def find_next_dose(self, *_):
        self.ensure_ready(); patient = self.repository.load(); now = self.clock.now(); meds = {m.id: m for m in self.repository.get_confirmed_medications()}
        upcoming = [l for l in patient.dose_logs if l.medication_id in meds and l.status in {"upcoming", "due"} and l.scheduled_at >= now]
        if not upcoming: return {"status": "none", "message": "According to your saved medication plan, there are no upcoming doses."}
        log = min(upcoming, key=lambda l: l.scheduled_at); med = meds[log.medication_id]
        return {"status": "upcoming", "dose_id": log.id, "medication": f"{med.patient_friendly_name}{' ' + med.strength if med.strength else ''}", "scheduled_at": log.scheduled_at.isoformat(), "message": f"According to your saved medication plan, the next dose is {med.patient_friendly_name}{' ' + med.strength if med.strength else ''} at {log.scheduled_at.strftime('%I:%M %p')}."}

    def check_dose_status(self, reference: str, *_):
        self.ensure_ready(); med = self._med(reference); today = self.clock.now().date()
        if med.schedule_type == "as_needed":
            return {"status": "as_needed", "message": f"According to your saved medication plan, {med.patient_friendly_name} is recorded as as-needed and has no recurring due time."}
        logs = [l for l in self.repository.load().dose_logs if l.medication_id == med.id and l.scheduled_at.date() == today]
        if not logs: return {"status": "not_scheduled", "message": "Your local dose ledger has no scheduled dose for that medication today."}
        log = min(logs, key=lambda l: l.scheduled_at)
        message = f"This medicine was logged as taken at {log.taken_at.strftime('%I:%M %p')}." if log.status in {"taken", "taken_late"} else f"Your local dose ledger records this dose as {log.status}."
        return {"status": log.status, "message": message}

    def mark_dose_taken(self, reference: str, *_):
        self.ensure_ready(); med = self._med(reference); patient = self.repository.load(); today = self.clock.now().date()
        logs = [l for l in patient.dose_logs if l.medication_id == med.id and l.scheduled_at.date() == today]
        if not logs: raise ValueError("No scheduled dose was found for that confirmed medication today.")
        log = min(logs, key=lambda l: abs((l.scheduled_at - self.clock.now()).total_seconds()))
        if log.status in {"taken", "taken_late"}: return {"status": "already_taken", "message": f"That dose was already recorded at {log.taken_at.strftime('%I:%M %p')}."}
        log.status = "taken"; log.taken_at = self.clock.now(); log.recorded_by = "patient"; log.source = "app_event"
        self.patients.save_patient(patient)
        return {"status": "taken", "message": f"The dose was recorded as taken at {log.taken_at.strftime('%I:%M %p')}."}

    def mark_dose_taken_by_id(self, dose_id: str):
        """Record one exact, confirmed dose instance selected by the user interface."""
        self.ensure_ready()
        patient = self.repository.load()
        confirmed = {m.id: m for m in self.repository.get_confirmed_medications()}
        log = next((item for item in patient.dose_logs if item.id == dose_id), None)
        if log is None or log.medication_id not in confirmed:
            raise ValueError("That scheduled dose was not found in the confirmed medication plan.")
        if log.scheduled_at.date() != self.clock.now().date():
            raise ValueError("Only a scheduled dose from today can be recorded from this dashboard.")
        if log.status in {"taken", "taken_late"}:
            return {
                "status": "already_taken",
                "dose_id": log.id,
                "message": f"That dose was already recorded at {log.taken_at.strftime('%I:%M %p')}.",
            }
        log.status = "taken"
        log.taken_at = self.clock.now()
        log.recorded_by = "patient"
        log.source = "app_event"
        self.patients.save_patient(patient)
        return {
            "status": "taken",
            "dose_id": log.id,
            "message": f"The {confirmed[log.medication_id].patient_friendly_name} dose was recorded as taken at {log.taken_at.strftime('%I:%M %p')}.",
        }

    def get_saved_instructions(self, reference: str):
        med = self._med(reference)
        return {"medication": med.patient_friendly_name, "instructions": med.source_instruction or "No verified instructions are saved.", "source": med.source}

    def show_medication_history(self, reference: str | None = None, limit: int = 10):
        self.ensure_ready(); med = self._med(reference) if reference else None
        medications = {m.id: m for m in self.repository.get_confirmed_medications()}
        now = self.clock.now()
        historical_statuses = {"taken", "taken_late", "missed", "skipped_by_user", "unknown"}
        return [{"medication_id": l.medication_id,
                 "medication": f"{medications[l.medication_id].patient_friendly_name}{' ' + medications[l.medication_id].strength if medications[l.medication_id].strength else ''}",
                 "scheduled_at": l.scheduled_at.isoformat(), "status": l.status,
                 "taken_at": l.taken_at.isoformat() if l.taken_at else ""}
                for l in self.repository.get_recent_dose_logs(len(self.repository.load().dose_logs))
                if l.medication_id in medications
                and (med is None or l.medication_id == med.id)
                and l.scheduled_at <= now
                and l.status in historical_statuses][:limit]
