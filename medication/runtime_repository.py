from __future__ import annotations

from medication.patient_data_service import PatientDataService
from medication.runtime import RuntimePatient
from medication.schemas import MedicationPlanItem


class RuntimeMedicationRepository:
    def __init__(self, patients: PatientDataService, patient_id: str) -> None:
        self.patients = patients
        self.patient_id = patient_id

    def load(self) -> RuntimePatient:
        return self.patients.reload_patient(self.patient_id)

    def get_confirmed_medications(self) -> list[MedicationPlanItem]:
        return [m for m in self.load().medication_plan.medications if m.current_use_status == "confirmed_current" and m.included_in_daily_plan and m.reconciliation_status == "verified"]

    def get_reconciled_medications(self) -> list[MedicationPlanItem]:
        """Confirmed plan entries, including non-recurring PRN entries."""
        return [m for m in self.load().medication_plan.medications if m.current_use_status == "confirmed_current" and m.reconciliation_status == "verified"]

    def get_verified_schedules(self) -> list[dict]:
        return [{"medication_id": m.id, "schedules": [s.model_dump(mode="json") for s in m.reminder_schedule]} for m in self.get_confirmed_medications()]

    def get_recent_dose_logs(self, limit: int = 20):
        return sorted(self.load().dose_logs, key=lambda x: x.scheduled_at, reverse=True)[:limit]

    def get_allergy_status(self) -> str:
        return self.load().source_record.allergy_status

    def get_source_medications_for_review(self) -> list[dict]:
        return list(self.load().source_record.medications)
