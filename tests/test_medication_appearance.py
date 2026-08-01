import pytest
from pydantic import ValidationError

from medication.clock import FixedClock
from medication.patient_data_service import PatientDataService
from medication.runtime import RuntimePatient
from medication.runtime_service import RuntimeMedicationService
from medication.schemas import MedicationAppearance, MedicationPlanItem
from scripts.prepare_demo_data import prepare_demo_data
from ui.gradio_app import _dashboard_html


def test_verified_appearance_validates_with_provenance():
    appearance = MedicationAppearance.model_validate({
        "description": "Small, round, white tablet.", "source": "caregiver_confirmed",
        "verification_status": "verified", "verified_by": "caregiver-1",
        "verified_at": "2026-08-01T09:00:00-04:00",
    })
    assert appearance.description == "Small, round, white tablet."


@pytest.mark.parametrize("appearance", [
    {"description": "White tablet.", "verification_status": "verified"},
    {"description": "White tablet.", "verification_status": "not_recorded"},
    {"color": ["white"], "verification_status": "not_recorded"},
    {"description": "   ", "verification_status": "unverified"},
])
def test_invalid_or_unattributed_appearance_is_rejected(appearance):
    with pytest.raises(ValidationError):
        MedicationAppearance.model_validate(appearance)


def test_absent_appearance_is_backward_compatible():
    item = MedicationPlanItem.model_validate({
        "id": "plan-1", "patient_friendly_name": "Example", "source": "explicit_reconciliation_record",
    })
    assert item.appearance is None


def test_demo_generation_carries_verified_profile_metadata_without_affecting_readiness(tmp_path):
    ready_path, unready_path = prepare_demo_data(tmp_path)
    ready = RuntimePatient.model_validate_json(ready_path.read_text())
    unready = RuntimePatient.model_validate_json(unready_path.read_text())
    descriptions = {med.patient_friendly_name: med.appearance.description for med in ready.medication_plan.medications}
    assert descriptions == {
        "Metoprolol succinate ER": "Small, round, white tablet.",
        "Metformin": "White, oval tablet.",
        "Vitamin D3": "Small, pale-yellow softgel capsule.",
    }
    assert all(med.appearance.source == "synthetic_reconciliation_profile" for med in ready.medication_plan.medications)
    assert ready.import_summary.ready_for_medication_tracking
    assert not unready.import_summary.ready_for_medication_tracking
    assert all(med.appearance is None for med in unready.medication_plan.medications)


def test_runtime_and_dashboard_expose_only_verified_appearance(tmp_path):
    prepare_demo_data(tmp_path)
    patients = PatientDataService(tmp_path)
    patient = patients.load_patient("demo-ready-001")
    metformin = next(med for med in patient.medication_plan.medications if med.patient_friendly_name == "Metformin")
    metformin.appearance = MedicationAppearance(description="Unverified visual note.", verification_status="unverified")
    patients.save_patient(patient)
    clock = FixedClock("2026-08-01T10:00:00-04:00")
    service = RuntimeMedicationService(patients, "demo-ready-001", clock)
    today = service.list_today_medications()
    assert next(item for item in today if item["name"] == "Metformin")["appearance"] is None
    assert service.find_next_dose()["appearance"] == "Small, pale-yellow softgel capsule."
    rendered = _dashboard_html(
        {"display_name": "Elena Rivera", "readiness": "Ready"}, today,
        service.find_next_dose(), clock.now(), [],
    )
    assert "Small, pale-yellow softgel capsule." in rendered
    assert "Small, round, white tablet." in rendered
    assert "Unverified visual note." not in rendered
    assert "Appearance can vary by manufacturer or refill" in rendered


def test_appearance_phrase_does_not_become_resolver_input(tmp_path):
    prepare_demo_data(tmp_path)
    service = RuntimeMedicationService(
        PatientDataService(tmp_path), "demo-ready-001", FixedClock("2026-08-01T10:00:00-04:00")
    )
    before = service.repository.load().model_dump_json()
    with pytest.raises(ValueError, match="No confirmed medication"):
        service.mark_dose_taken("pale-yellow softgel")
    assert service.repository.load().model_dump_json() == before
