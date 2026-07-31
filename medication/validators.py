from __future__ import annotations

from collections import Counter
from typing import Any

from medication.schemas import AllergySection, DoseLogRecord, MedicationPlanItem


def validate_patient_document(document: dict[str, Any]) -> dict[str, Any]:
    source = document.get("source_record", {})
    AllergySection(
        allergy_status=source.get("allergy_status", document.get("allergy_status", "not_recorded")),
        allergies=source.get("allergies", document.get("allergies", [])),
    )
    plan = [MedicationPlanItem.model_validate(item) for item in document.get("medication_plan", {}).get("medications", [])]
    plan_ids = {item.id for item in plan}
    logs = [DoseLogRecord.model_validate(item) for item in document.get("dose_logs", [])]
    missing = sorted({log.medication_id for log in logs} - plan_ids)
    if missing:
        raise ValueError(f"dose logs reference unknown medication ids: {', '.join(missing)}")
    keys = [(log.medication_id, log.scheduled_at.isoformat()) for log in logs]
    duplicates = [key for key, count in Counter(keys).items() if count > 1]
    if duplicates:
        raise ValueError("duplicate scheduled dose instances are not allowed")
    return document


def calculate_readiness(document: dict[str, Any]) -> dict[str, Any]:
    patient = document.get("source_record", {}).get("patient", document.get("patient", {}))
    meds = document.get("medication_plan", {}).get("medications", [])
    included = [m for m in meds if m.get("included_in_daily_plan")]
    blocking: list[str] = []
    warnings: list[str] = []
    if not any(m.get("current_use_status") == "confirmed_current" for m in meds):
        blocking.append("no_confirmed_current_medication_list")
    if meds and all(m.get("current_use_status") == "unverified" for m in meds):
        blocking.append("all_current_medications_unverified")
    if not included or any(not m.get("reminder_schedule") for m in included):
        blocking.append("no_verified_medication_schedule")
    conflict_types = {
        f.get("type") for f in document.get("source_record", {}).get("reconciliation_flags", [])
    }
    included_sources = {sid for m in included for sid in m.get("source_medication_request_ids", [])}
    conflicts = [
        f for f in document.get("source_record", {}).get("reconciliation_flags", [])
        if f.get("type") in {"same_normalized_ingredient_multiple_strengths", "possible_duplicate_order", "same_ingredient_multiple_orders"}
        and included_sources.intersection(f.get("related_medication_ids", []))
    ]
    if conflicts:
        blocking.append("unresolved_medication_conflicts")
    if not patient.get("timezone"):
        blocking.append("timezone_not_recorded")
    source = document.get("source_record", {})
    if source.get("allergy_status") == "not_recorded": warnings.append("allergy_status_not_recorded")
    source_meds = source.get("medications", source.get("medication_requests", []))
    if "possible_duplicate_order" in conflict_types: warnings.append("multiple_possible_duplicate_medications")
    if any("old_active_order" in m.get("validation_flags", []) for m in source_meds): warnings.append("historical_orders_still_marked_active")
    if any("missing_dosage_instruction" in m.get("validation_flags", []) for m in source_meds): warnings.append("missing_dosage_instructions")
    if any("missing_reason" in m.get("validation_flags", []) for m in source_meds): warnings.append("missing_medication_reasons")
    conditions = source.get("conditions", {})
    if conditions.get("social_context"): warnings.append("sensitive_conditions_excluded_from_ai_context")
    return {"ready_for_medication_tracking": not blocking, "blocking_issues": blocking, "warnings": warnings,
            "source": "deterministic_readiness_validation"}
