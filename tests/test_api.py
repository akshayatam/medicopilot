from pathlib import Path

from fastapi.testclient import TestClient

from scripts.prepare_demo_data import prepare_demo_data
from ui.api import create_api


class OfflineClient:
    base_url = "http://localhost:11434"
    model = "test-model"
    last_latency_ms = 0

    def chat(self, *_args, **_kwargs):
        raise AssertionError("unsafe requests must bypass the model")

    def health_check(self):
        return {"reachable": False, "model_available": False, "generation_ok": False}


def api_client(tmp_path: Path) -> TestClient:
    target = tmp_path / "patients"
    prepare_demo_data(target)
    return TestClient(create_api(OfflineClient(), target, "2026-08-01T10:00:00-04:00"))


def test_dashboard_is_structured_and_uses_verified_dose_ids(tmp_path):
    client = api_client(tmp_path)
    response = client.get("/api/patients/demo-ready-001/dashboard")
    assert response.status_code == 200
    payload = response.json()
    assert payload["readiness"]["ready_for_medication_tracking"] is True
    assert payload["next_dose"]["dose_id"].startswith("dose_plan_")
    assert payload["progress"] == {"completed": 1, "total": 3, "remaining": 2, "percent": 33}
    assert all(item["dose_id"] for item in payload["today"])


def test_dose_details_expose_only_verified_schedule_labels(tmp_path):
    client = api_client(tmp_path)
    payload = client.get("/api/patients/demo-ready-001/dashboard").json()
    details = payload["dose_details"]

    assert set(details) >= {item["dose_id"] for item in payload["today"]}
    for dose in payload["today"]:
        entry = details[dose["dose_id"]]
        assert set(entry) == {"period", "meal_context", "instruction", "purpose"}

    metoprolol = next(item for item in payload["today"] if item["name"].startswith("Metoprolol"))
    assert details[metoprolol["dose_id"]]["period"] == "morning"
    assert details[metoprolol["dose_id"]]["meal_context"] is None


def test_unready_dashboard_exposes_no_dose_labels(tmp_path):
    client = api_client(tmp_path)
    payload = client.get("/api/patients/demo-unready-001/dashboard").json()
    assert payload["dose_details"] == {}
    assert all("instruction" in item for item in payload["prn_medications"])


def test_exact_dose_confirmation_mutates_once_and_reloads_dashboard(tmp_path):
    client = api_client(tmp_path)
    dashboard = client.get("/api/patients/demo-ready-001/dashboard").json()
    dose_id = dashboard["next_dose"]["dose_id"]

    missing_confirmation = client.post(
        f"/api/patients/demo-ready-001/doses/{dose_id}/taken",
        json={"confirmed": False},
    )
    assert missing_confirmation.status_code == 422

    first = client.post(
        f"/api/patients/demo-ready-001/doses/{dose_id}/taken",
        json={"confirmed": True},
    )
    second = client.post(
        f"/api/patients/demo-ready-001/doses/{dose_id}/taken",
        json={"confirmed": True},
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["result"]["tool_output"]["status"] == "taken"
    assert second.json()["result"]["tool_output"]["status"] == "already_taken"
    assert first.json()["dashboard"]["progress"]["completed"] == 2


def test_unknown_or_non_today_dose_cannot_mutate(tmp_path):
    client = api_client(tmp_path)
    unknown = client.post(
        "/api/patients/demo-ready-001/doses/not-a-dose/taken",
        json={"confirmed": True},
    )
    assert unknown.status_code == 409
    assert "not found" in unknown.json()["detail"]

    historical = client.post(
        "/api/patients/demo-ready-001/doses/dose_plan_src_vitamin_d_20260731T1300-0400/taken",
        json={"confirmed": True},
    )
    assert historical.status_code == 409
    assert "from today" in historical.json()["detail"]

    source = client.get("/api/patients/demo-ready-001/dashboard").json()["today"]
    assert all(item["scheduled_at"].startswith("2026-08-01") for item in source)


def test_unready_dashboard_never_uses_source_orders(tmp_path):
    client = api_client(tmp_path)
    response = client.get("/api/patients/demo-unready-001/dashboard")
    payload = response.json()
    assert payload["readiness"]["ready_for_medication_tracking"] is False
    assert payload["today"]["status"] == "review_required"
    assert payload["today"]["message"]
    assert payload["progress"]["total"] == 0


def test_unsafe_chat_remains_deterministic_and_non_mutating(tmp_path):
    client = api_client(tmp_path)
    before = client.get("/api/patients/demo-ready-001/dashboard").json()
    response = client.post(
        "/api/patients/demo-ready-001/ask",
        json={"text": "Should I double my dose?", "simplified": True},
    )
    after = client.get("/api/patients/demo-ready-001/dashboard").json()
    assert response.status_code == 200
    assert response.json()["result"]["outcome"] == "unsafe_request"
    assert "cannot recommend" in response.json()["answer"]
    assert before["today"] == after["today"]


def test_common_schedule_question_works_without_local_model(tmp_path):
    client = api_client(tmp_path)
    response = client.post(
        "/api/patients/demo-ready-001/ask",
        json={"text": "what does my schedule look like?", "simplified": False},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["action"] == "LIST_TODAY_MEDICATIONS"
    assert payload["result"]["model_latency_ms"] is None
    assert "Metoprolol" in payload["answer"]
    assert "Vitamin D3" in payload["answer"]


def test_common_next_medication_question_works_without_local_model(tmp_path):
    client = api_client(tmp_path)
    response = client.post(
        "/api/patients/demo-ready-001/ask",
        json={"text": "What is my next medication?", "simplified": False},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["action"] == "FIND_NEXT_DOSE"
    assert payload["result"]["model_latency_ms"] is None
    assert "Vitamin D3" in payload["answer"]
    assert "01:00 PM" in payload["answer"]
