import json

import pytest

from gemma.patient_qa import PatientQuestionAnswerer
from medication.patient_records import PatientRecordStore


def _write_patient(directory, patient_id="patient-1", name="Test Person"):
    data = {
        "patient": {
            "id": patient_id,
            "display_name": name,
            "birth_date": "1950-01-01",
            "age_at_dataset_reference_date": 76,
            "gender": "female",
            "preferred_language": "en-US",
        },
        "conditions": {"clinical_conditions": [{"display": "Example condition"}]},
        "allergies": [],
        "allergy_status": "not_recorded",
        "medications": [{"id": "med-1", "name": "Example medicine", "active": True}],
        "dose_logs": [],
    }
    path = directory / f"{name}_{patient_id}.medication-copilot.json"
    path.write_text(json.dumps(data), encoding="utf-8")


def test_indexes_loads_and_summarizes_patient_records(tmp_path):
    _write_patient(tmp_path)
    store = PatientRecordStore(tmp_path)

    assert store.list_patients()[0].label == "Test Person (female, age 76)"
    assert store.overview("patient-1")["active_conditions"] == 1
    assert store.overview("patient-1")["active_medications"] == 1
    assert store.load("patient-1")["patient"]["display_name"] == "Test Person"


def test_rejects_unknown_patient_key(tmp_path):
    _write_patient(tmp_path)
    store = PatientRecordStore(tmp_path)

    with pytest.raises(ValueError, match="valid patient"):
        store.load("../../another-file")


def test_question_answerer_sends_selected_record_as_plain_text(tmp_path):
    _write_patient(tmp_path)
    store = PatientRecordStore(tmp_path)

    class FakeClient:
        last_latency_ms = 4

        def chat(self, system, user, json_output=True):
            self.call = (system, user, json_output)
            return "Grounded answer"

    client = FakeClient()
    answer = PatientQuestionAnswerer(client, store).answer(
        "patient-1", " What conditions are recorded? "
    )

    assert answer == "Grounded answer"
    assert '"display":"Example condition"' in client.call[1]
    assert client.call[2] is False


def test_ai_context_excludes_sensitive_and_bulk_fhir_data(tmp_path):
    _write_patient(tmp_path)
    path = next(tmp_path.glob("*.json"))
    data = json.loads(path.read_text())
    data["patient"]["address"] = [{"line": ["123 Exact Street"]}]
    data["conditions"]["social_context"] = [{"display": "Sensitive social circumstance"}]
    data["claims"] = [{"amount": 100}]
    data["raw_fhir_bundle"] = "must-not-leak"
    path.write_text(json.dumps(data))
    context = PatientRecordStore(tmp_path).llm_context("patient-1")
    assert "123 Exact Street" not in context
    assert "Sensitive social circumstance" not in context
    assert "claims" not in context
    assert "must-not-leak" not in context
