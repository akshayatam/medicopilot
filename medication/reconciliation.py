from __future__ import annotations

from typing import Any

from medication.schemas import ReconciliationProfile


def detect_conflicts(medications: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    by_ingredient: dict[str, list[dict[str, Any]]] = {}
    by_signature: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for med in medications:
        names = [i.get("name") for i in med.get("ingredients", []) if i.get("name")]
        if not names and med.get("patient_friendly_name"):
            names = [str(med["patient_friendly_name"]).casefold()]
        for name in names:
            by_ingredient.setdefault(name.casefold(), []).append(med)
        signature = (med.get("rxnorm_code"), med.get("raw_display"), med.get("fhir_status"), med.get("authored_on"))
        by_signature.setdefault(signature, []).append(med)
    for group in by_ingredient.values():
        ids = sorted({m["id"] for m in group})
        if len(ids) < 2:
            continue
        strengths = {str(m.get("strength")).casefold() for m in group if m.get("strength")}
        kind = "same_normalized_ingredient_multiple_strengths" if len(strengths) > 1 else "same_ingredient_multiple_orders"
        flags.append({"type": kind, "related_medication_ids": ids, "source": "deterministic_conflict_detection"})
        flags.append({"type": "possible_replacement_or_renewal", "related_medication_ids": ids, "source": "deterministic_conflict_detection"})
    for group in by_signature.values():
        ids = sorted({m["id"] for m in group})
        if len(ids) > 1:
            flags.append({"type": "possible_duplicate_order", "related_medication_ids": ids, "source": "deterministic_conflict_detection"})
    return flags


def apply_reconciliation(document: dict[str, Any], profile_data: dict[str, Any]) -> dict[str, Any]:
    profile = ReconciliationProfile.model_validate(profile_data)
    patient = document.get("source_record", {}).get("patient", {})
    if profile.patient_id != patient.get("id"):
        raise ValueError("reconciliation profile patient_id does not match source record")
    source_record = document.get("source_record", {})
    requests = {m["id"]: m for m in source_record.get("medications", source_record.get("medication_requests", []))}
    plan: list[dict[str, Any]] = []
    for decision in profile.decisions:
        source = requests.get(decision.medication_request_id)
        if source is None:
            raise ValueError(f"unknown MedicationRequest: {decision.medication_request_id}")
        if decision.reminder_schedule and source.get("schedule_type") == "as_needed":
            raise ValueError("as-needed medication cannot receive a recurring reminder")
        if decision.included_in_daily_plan and not decision.reminder_schedule:
            raise ValueError("included medication requires a verified reminder schedule")
        plan.append({
            "id": f"plan_{source['id']}",
            "source_medication_request_ids": [source["id"]],
            "patient_friendly_name": decision.patient_friendly_name or source.get("patient_friendly_name") or source.get("raw_display"),
            "aliases": decision.aliases,
            "strength": source.get("strength"),
            "purpose_labels": decision.purpose_labels if decision.purpose_labels is not None else source.get("purpose_labels", []),
            "purpose_source": "verified_reconciliation" if decision.purpose_labels is not None else source.get("purpose_source", "not_recorded"),
            "source_instruction": source.get("source_instruction"),
            "appearance": decision.appearance.model_dump(mode="json") if decision.appearance else None,
            "schedule_type": source.get("schedule_type", "unknown"),
            "reminder_schedule": [s.model_dump(mode="json") for s in decision.reminder_schedule],
            "current_use_status": decision.current_use_status,
            "included_in_daily_plan": decision.included_in_daily_plan,
            "reconciliation_status": "verified",
            "verified_by": decision.verified_by,
            "verified_at": decision.verified_at.isoformat(),
            "source": decision.source,
        })
    document["medication_plan"] = {"medications": plan, "source": profile.source}
    return document
