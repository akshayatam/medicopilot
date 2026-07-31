from argparse import Namespace
from datetime import date

import pytest
from pydantic import ValidationError

from medication.adherence_simulator import simulate_adherence
from medication.fhir_converter import convert_bundle
from medication.plan_builder import build_plan, generate_scheduled_doses
from medication.reconciliation import apply_reconciliation
from medication.schemas import AllergySection, DoseLogRecord, MedicationPlanItem
from medication.validators import calculate_readiness, validate_patient_document


def _args(**overrides):
    values = dict(as_of_date=date(2026, 7, 28), min_age=60, default_timezone="America/New_York", include_all_conditions=True, include_inactive_medications=True, old_active_order_days=730)
    values.update(overrides)
    return Namespace(**values)


def _bundle(*resources):
    patient = {"resourceType": "Patient", "id": "p1", "birthDate": "1950-01-01", "name": [{"use": "official", "given": ["Pat"], "family": "Example"}]}
    return {"resourceType": "Bundle", "type": "collection", "entry": [{"resource": r} for r in (patient, *resources)]}


def _med(mid="1", display="Drug 10 MG Tablet", status="active", dosage=None, reason=None):
    value = {"resourceType": "MedicationRequest", "id": mid, "status": status, "intent": "order", "authoredOn": "2020-01-01", "medicationCodeableConcept": {"coding": [{"system": "http://www.nlm.nih.gov/research/umls/rxnorm", "code": mid, "display": display}]}}
    if dosage is not None: value["dosageInstruction"] = [dosage]
    if reason is not None: value["reasonCode"] = [{"text": reason}]
    return value


def _converted(*resources):
    return convert_bundle(_bundle(*resources), _args())


def _profile(document, schedule=True):
    reminder = [{"time": "08:00", "source": "synthetic_reconciliation_profile", "verified": True, "verified_by": "synthetic_caregiver", "verified_at": "2026-07-28T14:00:00-04:00"}] if schedule else []
    return {"patient_id": "p1", "source": "synthetic_reconciliation_profile", "decisions": [{"medication_request_id": document["source_record"]["medications"][0]["id"], "current_use_status": "confirmed_current", "included_in_daily_plan": schedule, "reminder_schedule": reminder, "verified_by": "synthetic_caregiver", "verified_at": "2026-07-28T14:00:00-04:00", "source": "synthetic_reconciliation_profile"}]}


def test_under_60_and_deceased_patients_are_skipped():
    young = _bundle(); young["entry"][0]["resource"]["birthDate"] = "1980-01-01"
    assert convert_bundle(young, _args()) is None
    deceased = _bundle(); deceased["entry"][0]["resource"]["deceasedBoolean"] = True
    assert convert_bundle(deceased, _args()) is None
    invalid = _bundle(); invalid["entry"][0]["resource"]["birthDate"] = "not-a-date"
    assert convert_bundle(invalid, _args()) is None


def test_missing_and_explicit_no_known_allergies_are_distinct():
    assert _converted()["source_record"]["allergy_status"] == "not_recorded"
    nka = {"resourceType": "AllergyIntolerance", "id": "a", "code": {"coding": [{"code": "716186003", "display": "No known allergy"}]}}
    assert _converted(nka)["source_record"]["allergy_status"] == "no_known_allergies_explicitly_recorded"


def test_recorded_allergy_reaction_and_invalid_cross_fields():
    allergy = {"resourceType": "AllergyIntolerance", "id": "a", "code": {"text": "Peanut"}, "reaction": [{"manifestation": [{"text": "Hives"}], "severity": "moderate"}]}
    result = _converted(allergy)["source_record"]
    assert result["allergies"][0]["reactions"][0]["manifestations"] == ["Hives"]
    with pytest.raises(ValidationError): AllergySection(allergy_status="recorded", allergies=[])


def test_imported_orders_remain_unverified_and_missing_fields_are_flagged():
    med = _converted(_med())["source_record"]["medications"][0]
    assert med["fhir_status"] == "active"
    assert med["current_use_status"] == "unverified"
    assert med["included_in_daily_plan"] is False
    assert {"missing_dosage_instruction", "missing_reason", "old_active_order"} <= set(med["validation_flags"])


def test_prn_and_frequency_only_never_create_reminders_but_exact_time_is_retained():
    prn = _med("p", dosage={"text": "Take as needed."})
    frequency = _med("f", dosage={"timing": {"repeat": {"frequency": 1, "period": 1, "periodUnit": "d"}}})
    exact = _med("e", dosage={"timing": {"repeat": {"timeOfDay": ["08:00"]}}})
    meds = {m["fhir_resource_id"]: m for m in _converted(prn, frequency, exact)["source_record"]["medications"]}
    assert meds["p"]["schedule_type"] == "as_needed" and meds["p"]["source_schedules"] == []
    assert meds["f"]["source_schedules"] == []
    assert meds["e"]["source_schedules"][0]["source"] == "FHIR dosageInstruction.timing.repeat.timeOfDay"


def test_complex_display_is_preserved_and_warned():
    med = _converted(_med(display="Drug A 10 MG / Drug B 5 MG Tablet"))["source_record"]["medications"][0]
    assert med["raw_display"] == "Drug A 10 MG / Drug B 5 MG Tablet"
    assert "medication_display_not_fully_normalized" in med["validation_flags"]


def test_same_ingredient_strength_conflict_is_flagged_not_resolved():
    result = _converted(_med("a", "Example 5 MG Tablet"), _med("b", "Example 10 MG Tablet"))
    flags = result["source_record"]["reconciliation_flags"]
    assert any(f["type"] == "same_normalized_ingredient_multiple_strengths" for f in flags)
    assert result["medication_plan"]["medications"] == []


def test_clinical_administration_stays_out_of_home_logs():
    admin = {"resourceType": "MedicationAdministration", "id": "a1", "status": "completed", "effectiveDateTime": "2026-01-01T10:00:00Z"}
    result = _converted(admin)
    assert result["source_record"]["clinical_administrations"][0]["eligible_as_home_adherence_log"] is False
    assert result["dose_logs"] == []


def test_reconciliation_plan_generation_and_readiness():
    document = _converted(_med(dosage={"timing": {"repeat": {"frequency": 1, "period": 1, "periodUnit": "d"}}}))
    apply_reconciliation(document, _profile(document)); build_plan(document)
    document["import_summary"] = calculate_readiness(document)
    assert document["import_summary"]["ready_for_medication_tracking"] is True
    doses = generate_scheduled_doses(document, date(2026, 8, 1), 2)
    assert len(doses) == 2 and all(x["source"] == "app_event" for x in doses)


def test_unverified_missing_schedule_and_prn_cannot_enter_plan():
    with pytest.raises(ValidationError):
        MedicationPlanItem(id="x", patient_friendly_name="X", included_in_daily_plan=True, current_use_status="unverified", reconciliation_status="needs_review", source="explicit_reconciliation_record")
    document = _converted(_med(dosage={"asNeededBoolean": True, "text": "as needed"}))
    with pytest.raises(ValueError, match="as-needed"):
        apply_reconciliation(document, _profile(document))


def test_timezone_required_and_simulation_is_reproducible():
    document = _converted(_med(dosage={"text": "once daily"}))
    apply_reconciliation(document, _profile(document)); build_plan(document)
    document["source_record"]["patient"]["timezone"] = None
    with pytest.raises(ValueError, match="timezone"):
        generate_scheduled_doses(document, date(2026, 8, 1), 1)
    document["source_record"]["patient"]["timezone"] = "America/New_York"
    doses = generate_scheduled_doses(document, date(2026, 8, 1), 3)
    assert simulate_adherence(doses, 42) == simulate_adherence(doses, 42)


def test_dose_cross_fields_unknown_reference_and_duplicates_rejected():
    with pytest.raises(ValidationError): DoseLogRecord(id="x", medication_id="m", scheduled_at="2026-01-01T08:00:00Z", status="taken", source="app_event")
    with pytest.raises(ValidationError): DoseLogRecord(id="x", medication_id="m", scheduled_at="2026-01-01T08:00:00Z", status="upcoming", taken_at="2026-01-01T08:01:00Z", source="app_event")
    document = _converted()
    document["dose_logs"] = [{"id": "x", "medication_id": "missing", "scheduled_at": "2026-01-01T08:00:00Z", "status": "unknown", "source": "app_event"}]
    with pytest.raises(ValueError, match="unknown medication"): validate_patient_document(document)
