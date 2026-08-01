from __future__ import annotations

from datetime import datetime, timedelta

from medication.clock import Clock
from medication.dose_status import DoseStatusPolicy, MissedDoseResult, calculate_effective_dose_status
from medication.patient_data_service import PatientDataService
from medication.resolver import MedicationResolution, MedicationResolver, ResolutionStatus
from medication.runtime_repository import RuntimeMedicationRepository

UNREADY_MESSAGE = "The medication plan has not been verified yet. Complete medication review before using reminders or dose tracking."


class RuntimeMedicationService:
    def __init__(self, patients: PatientDataService, patient_id: str, clock: Clock, policy: DoseStatusPolicy | None = None) -> None:
        self.patients = patients; self.patient_id = patient_id; self.clock = clock
        self.repository = RuntimeMedicationRepository(patients, patient_id)
        self.resolver = MedicationResolver()
        self.policy = policy or DoseStatusPolicy()

    def policy_payload(self) -> dict[str, int]:
        return self.policy.model_dump()

    def patient_data_version(self) -> str:
        summary = next(item for item in self.patients.list_available_patients() if item.patient_id == self.patient_id)
        stat = summary.path.stat()
        return f"{stat.st_ino}:{stat.st_size}:{stat.st_mtime_ns}"

    def effective_status(self, dose, now: datetime | None = None) -> str:
        return calculate_effective_dose_status(dose, now or self.clock.now(), self.policy)

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

    @staticmethod
    def _verified_appearance(med) -> str | None:
        appearance = med.appearance
        if appearance and appearance.verification_status == "verified":
            return appearance.description
        return None

    def list_today_medications(self, *_):
        self.ensure_ready(); patient = self.repository.load(); now = self.clock.now(); today = now.date()
        meds = {m.id: m for m in self.repository.get_confirmed_medications()}
        results = [{"medication_id": l.medication_id, "name": meds[l.medication_id].patient_friendly_name, "strength": meds[l.medication_id].strength or "", "appearance": self._verified_appearance(meds[l.medication_id]), "scheduled_at": l.scheduled_at.isoformat(), "stored_status": l.status, "effective_status": self.effective_status(l, now), "status": self.effective_status(l, now), "taken_at": l.taken_at.isoformat() if l.taken_at else "", "dose_status_policy": self.policy_payload()} for l in patient.dose_logs if l.medication_id in meds and l.scheduled_at.date() == today]
        if not results:
            return {"status": "no_data", "date": today.isoformat(), "message": f"No dose instances are stored for {today.isoformat()}. No other date was substituted."}
        return results

    def find_next_dose(self, *_):
        self.ensure_ready(); patient = self.repository.load(); now = self.clock.now(); meds = {m.id: m for m in self.repository.get_confirmed_medications()}
        upcoming = [l for l in patient.dose_logs if l.medication_id in meds and self.effective_status(l, now) in {"upcoming", "due"}]
        if not upcoming: return {"status": "none", "message": "According to your saved medication plan, there are no upcoming doses."}
        log = min(upcoming, key=lambda l: l.scheduled_at); med = meds[log.medication_id]
        effective = self.effective_status(log, now)
        return {"status": effective, "stored_status": log.status, "effective_status": effective, "medication_id": med.id, "medication": f"{med.patient_friendly_name}{' ' + med.strength if med.strength else ''}", "appearance": self._verified_appearance(med), "scheduled_at": log.scheduled_at.isoformat(), "dose_status_policy": self.policy_payload(), "message": f"According to your saved medication plan, the next dose is {med.patient_friendly_name}{' ' + med.strength if med.strength else ''} at {log.scheduled_at.strftime('%I:%M %p')}."}

    def check_dose_status(self, reference: str, *_):
        self.ensure_ready(); med = self._med(reference); now = self.clock.now(); today = now.date()
        if med.schedule_type == "as_needed":
            return {"status": "as_needed", "message": f"According to your saved medication plan, {med.patient_friendly_name} is recorded as as-needed and has no recurring due time."}
        logs = [l for l in self.repository.load().dose_logs if l.medication_id == med.id and l.scheduled_at.date() == today]
        if not logs: return {"status": "not_scheduled", "message": "Your local dose ledger has no scheduled dose for that medication today."}
        log = min(logs, key=lambda l: l.scheduled_at)
        effective = self.effective_status(log, now)
        message = f"This medicine was logged as taken at {log.taken_at.strftime('%I:%M %p')}." if effective in {"taken", "taken_late"} else f"Your local dose ledger records this scheduled dose as {effective.replace('_', ' ')}; no taken record exists."
        return {"status": effective, "stored_status": log.status, "effective_status": effective, "scheduled_at": log.scheduled_at.isoformat(), "dose_status_policy": self.policy_payload(), "message": message}

    def mark_dose_taken(self, reference: str, *_):
        self.ensure_ready(); med = self._med(reference); patient = self.repository.load(); today = self.clock.now().date()
        logs = [l for l in patient.dose_logs if l.medication_id == med.id and l.scheduled_at.date() == today]
        if not logs: raise ValueError("No scheduled dose was found for that confirmed medication today.")
        log = min(logs, key=lambda l: abs((l.scheduled_at - self.clock.now()).total_seconds()))
        return self._record_exact(patient, med, log)

    def mark_exact_dose_taken(self, medication_id: str, scheduled_at: datetime):
        self.ensure_ready(); patient = self.repository.load()
        meds = {m.id: m for m in self.repository.get_confirmed_medications()}
        med = meds.get(medication_id)
        if med is None:
            raise ValueError("The confirmed medication for this pending action is no longer available.")
        exact = [l for l in patient.dose_logs if l.medication_id == medication_id and l.scheduled_at == scheduled_at]
        if len(exact) != 1:
            raise ValueError("The exact scheduled dose could not be revalidated.")
        return self._record_exact(patient, med, exact[0])

    def _record_exact(self, patient, med, log):
        if log.status in {"taken", "taken_late"}:
            return {"status": "already_taken", "message": "That dose was already recorded as taken."}
        now = self.clock.now()
        late_after = log.scheduled_at + timedelta(minutes=self.policy.due_window_minutes)
        log.status = "taken_late" if now > late_after else "taken"
        log.taken_at = now; log.recorded_by = "patient"; log.source = "app_event"
        self.patients.save_patient(patient)
        display = f"{med.patient_friendly_name}{' ' + med.strength if med.strength else ''}"
        return {"status": log.status, "medication_id": med.id, "scheduled_at": log.scheduled_at.isoformat(), "message": f"{display} scheduled for {log.scheduled_at.strftime('%-I:%M %p')} has been recorded as taken."}

    def check_missed_doses(self, *_):
        self.ensure_ready(); now = self.clock.now(); today = now.date(); patient = self.repository.load()
        meds = {m.id: m for m in self.repository.get_confirmed_medications()}
        scheduled = [l for l in patient.dose_logs if l.medication_id in meds and l.scheduled_at.date() == today]
        if not scheduled:
            return MissedDoseResult(status="no_schedule_data", date=today.isoformat(), message=f"No dose instances are stored for {today.isoformat()}.", dose_status_policy=self.policy).model_dump(mode="json")
        missed = []
        for log in sorted(scheduled, key=lambda item: item.scheduled_at):
            if self.effective_status(log, now) != "missed":
                continue
            med = meds[log.medication_id]
            missed.append({"medication_id": med.id, "name": med.patient_friendly_name, "strength": med.strength or "", "scheduled_at": log.scheduled_at, "stored_status": log.status})
        if not missed:
            return MissedDoseResult(status="no_missed_doses", date=today.isoformat(), message="Your local dose log does not show any missed scheduled doses today.", dose_status_policy=self.policy).model_dump(mode="json")
        if len(missed) == 1:
            dose = missed[0]; display = f"{dose['name']}{' ' + dose['strength'] if dose['strength'] else ''}"
            message = f"{display} was scheduled for {dose['scheduled_at'].strftime('%-I:%M %p')} and is not recorded as taken. Did you take it? I can record that dose as taken."
        else:
            rows = "\n".join(f"- {dose['name']}{' ' + dose['strength'] if dose['strength'] else ''} — {dose['scheduled_at'].strftime('%-I:%M %p')}" for dose in missed)
            message = f"I found {len(missed)} scheduled doses that are not recorded as taken:\n{rows}\nWhich medicine would you like to review?"
        return MissedDoseResult(status="missed_doses_found", date=today.isoformat(), doses=missed, message=message, dose_status_policy=self.policy).model_dump(mode="json")

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
                 "scheduled_at": l.scheduled_at.isoformat(), "stored_status": l.status, "effective_status": self.effective_status(l, now), "status": self.effective_status(l, now),
                 "taken_at": l.taken_at.isoformat() if l.taken_at else ""}
                for l in self.repository.get_recent_dose_logs(len(self.repository.load().dose_logs))
                if l.medication_id in medications
                and (med is None or l.medication_id == med.id)
                and l.scheduled_at <= now
                and self.effective_status(l, now) in historical_statuses][:limit]
