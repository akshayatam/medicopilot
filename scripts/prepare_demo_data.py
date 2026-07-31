#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from medication.plan_builder import build_plan, generate_scheduled_doses
from medication.reconciliation import apply_reconciliation
from medication.runtime import RuntimePatient
from medication.validators import calculate_readiness


def med(mid: str, name: str, strength: str, instruction: str) -> dict:
    return {"id": mid, "fhir_resource_id": mid.removeprefix("src_"), "raw_display": f"{name} {strength}", "patient_friendly_name": name,
            "ingredients": [{"name": name.casefold(), "strength": strength.casefold()}], "strength": strength,
            "purpose_labels": [], "purpose_source": "not_recorded", "source_instruction": instruction,
            "schedule_type": "scheduled", "fhir_status": "active", "current_use_status": "unverified",
            "included_in_daily_plan": False, "reconciliation_status": "needs_review", "validation_flags": ["missing_reason"],
            "source": "synthetic_demo_source_record"}


def source(patient_id: str, name: str, medications: list[dict], timezone: str = "America/New_York") -> dict:
    return {"schema_version": "2.0", "source_record": {"patient": {"id": patient_id, "display_name": name, "birth_date": "1950-01-01", "age_at_dataset_reference_date": 76, "gender": "female", "preferred_language": "en-US", "timezone": timezone},
            "conditions": {"clinical_conditions": [], "historical_conditions": [], "social_context": [{"display": "Sensitive synthetic social context", "visibility": {"include_in_medication_context": False, "show_in_patient_ui": False}}], "administrative_flags": []},
            "allergies": [], "allergy_status": "not_recorded", "medications": medications,
            "clinical_administrations": [], "reconciliation_flags": [], "provenance": {"source": "curated_synthetic_demo_source"}},
            "medication_plan": {"medications": [], "source": "not_reconciled"}, "dose_logs": [],
            "support_profile": {"caregiver": None, "preferred_response_language": "en-US", "accessibility": {"large_text": True, "high_contrast": True, "voice_enabled": False}, "confirmation_style": "explicit"}, "provenance": {"source": "curated_synthetic_demo_builder"}}


def canonical(document: dict) -> dict:
    document["medication_plan"]["patient_id"] = document["source_record"]["patient"]["id"]
    document["medication_plan"]["status"] = "verified" if document["import_summary"]["ready_for_medication_tracking"] else "needs_review"
    document["medication_plan"].pop("daily_medication_ids", None)
    return document


def main() -> None:
    output = ROOT / "data" / "runtime_patients"; output.mkdir(parents=True, exist_ok=True)
    ready = source("demo-ready-001", "Elena Rivera", [med("src_metoprolol", "Metoprolol succinate ER", "100 mg", "Take according to the verified saved plan."), med("src_metformin", "Metformin", "500 mg", "Take according to the verified saved plan."), med("src_vitamin_d", "Vitamin D3", "1000 IU", "Take according to the verified saved plan.")])
    profile = json.loads((ROOT / "data/reconciliation/ready_demo.json").read_text())
    apply_reconciliation(ready, profile); build_plan(ready); ready["import_summary"] = calculate_readiness(ready)
    logs = generate_scheduled_doses(ready, date(2026, 7, 31), 2)
    for log in logs:
        if log["scheduled_at"].startswith("2026-07-31T08:00"): log.update(status="taken_late", taken_at="2026-07-31T09:00:00-04:00", recorded_by="synthetic_simulator", source="synthetic_adherence_simulation", generation_parameters={"seed": 42, "statement": "Synthetic demo scenario; not a real-world statistic."})
        elif log["scheduled_at"].startswith("2026-07-31"): log.update(status="missed")
        elif log["scheduled_at"].startswith("2026-08-01T08:00"): log.update(status="taken", taken_at="2026-08-01T08:11:00-04:00", recorded_by="synthetic_simulator", source="synthetic_adherence_simulation", generation_parameters={"seed": 42, "statement": "Synthetic demo scenario; not a real-world statistic."})
    ready["dose_logs"] = logs
    ready = canonical(ready); RuntimePatient.model_validate(ready)
    (output / "ready.runtime.json").write_text(json.dumps(ready, indent=2) + "\n")

    unready = source("demo-unready-001", "Marcus Chen", [med("src_order_a", "Example medicine", "5 mg", "No verified schedule recorded."), med("src_order_b", "Example medicine", "10 mg", "No verified schedule recorded.")])
    unready["source_record"]["reconciliation_flags"] = [{"type": "same_normalized_ingredient_multiple_strengths", "related_medication_ids": ["src_order_a", "src_order_b"], "source": "deterministic_conflict_detection"}]
    unready["import_summary"] = calculate_readiness(unready); unready = canonical(unready); RuntimePatient.model_validate(unready)
    (output / "unready.runtime.json").write_text(json.dumps(unready, indent=2) + "\n")


if __name__ == "__main__": main()
