import shutil
from datetime import datetime
from pathlib import Path

import pytest
from fastapi import HTTPException

from backend.app import create_app
from backend.app import ChatRequest, DirectActionRequest, SessionRequest


class OfflineClient:
    base_url = "http://localhost:11434"
    model = "gemma4:e2b"
    timeout = 1
    last_latency_ms = None

    def health_check(self):
        return {"reachable": False, "model_available": False, "generation_ok": False}

    def chat(self, *_args, **_kwargs):
        raise AssertionError("deterministic API checks must not invoke the model")


class MissedDoseClient(OfflineClient):
    def chat(self, *_args, **_kwargs):
        return '{"action":"CHECK_MISSED_DOSES","medication_reference":null,"date_reference":"today","time_period":null,"clarification_question":null,"unsafe_reason":null}'


def platform(tmp_path, *, now="2026-08-01T10:00:00-04:00", client=None):
    directory = tmp_path / "patients"
    shutil.copytree(Path(__file__).parents[1] / "data" / "runtime_patients", directory)
    app = create_app(
        patients_directory=directory,
        demo_now=now,
        client=client or OfflineClient(),
    )
    return app, directory


def endpoint(app, path):
    return next(route.endpoint for route in app.routes if getattr(route, "path", None) == path)


def stage_missed_confirmation(tmp_path):
    app, directory = platform(
        tmp_path, now="2026-08-01T13:58:00-04:00", client=MissedDoseClient()
    )
    result = endpoint(app, "/api/chat")(ChatRequest(
        patient_id="demo-ready-001", text="Have I missed any medicine?"
    ))
    assert result["pending_confirmation"]["type"] == "record_missed_dose_as_taken"
    return app, directory, result["session_id"]


def test_dashboard_matches_runtime_deterministic_state(tmp_path):
    app, _ = platform(tmp_path)
    payload = endpoint(app, "/api/patients/{patient_id}/dashboard")("demo-ready-001")
    assert payload["patient"]["display_name"] == "Elena Rivera"
    assert payload["next_dose"]["medication"] == "Vitamin D3 1000 IU"
    assert payload["progress"] == {"completed": 1, "total": 3, "missed": 0, "remaining": 2}
    assert [item["status"] for item in payload["today"]] == ["taken", "upcoming", "upcoming"]


def test_direct_mutation_advances_shared_runtime_state(tmp_path):
    app, directory = platform(tmp_path)
    request = {"patient_id": "demo-ready-001", "action": "mark_next"}
    action = endpoint(app, "/api/actions")
    first = action(DirectActionRequest.model_validate(request))
    second = action(DirectActionRequest.model_validate(request))
    assert first["answer"].endswith("has been recorded as taken.")
    assert "Vitamin D3" in first["answer"] and "Metformin" in second["answer"]
    assert '"status": "taken"' in (directory / "ready.runtime.json").read_text()


def test_unready_and_source_review_preserve_boundaries(tmp_path):
    app, _ = platform(tmp_path)
    dashboard = endpoint(app, "/api/patients/{patient_id}/dashboard")("demo-unready-001")
    review = endpoint(app, "/api/patients/{patient_id}/source-review")("demo-unready-001")
    assert dashboard["patient"]["readiness"] == "Needs review"
    assert dashboard["today"]["status"] == "review_required"
    assert review["items"] and not any(item["included_in_plan"] for item in review["items"])


def test_debug_is_developer_opt_in(tmp_path):
    app, _ = platform(tmp_path)
    base = {"patient_id": "demo-ready-001", "action": "next"}
    action = endpoint(app, "/api/actions")
    normal = action(DirectActionRequest.model_validate(base))
    debug = action(DirectActionRequest.model_validate(base | {"include_debug": True}))
    assert "debug" not in normal
    assert debug["debug"]["tool_output"]["medication"] == "Vitamin D3 1000 IU"


def test_affirmative_confirmation_updates_exact_dose_and_dashboard_progress(tmp_path):
    app, _, session_id = stage_missed_confirmation(tmp_path)
    confirm = endpoint(app, "/api/confirmations/missed-dose")
    result = confirm(SessionRequest(patient_id="demo-ready-001", session_id=session_id))
    assert result["answer"] == "Vitamin D3 1000 IU scheduled for 1:00 PM has been recorded as taken."
    assert result["tool_output"] if "tool_output" in result else True
    dashboard = endpoint(app, "/api/patients/{patient_id}/dashboard")("demo-ready-001")
    vitamin = next(item for item in dashboard["today"] if item["name"] == "Vitamin D3")
    assert vitamin["status"] == "taken_late"
    assert dashboard["progress"] == {"completed": 2, "total": 3, "missed": 0, "remaining": 1}
    state = app.state.session_store._values[session_id]
    assert "pending_dose_followup" not in state


def test_duplicate_confirmation_is_replay_safe_and_creates_no_duplicate(tmp_path):
    app, _, session_id = stage_missed_confirmation(tmp_path)
    confirm = endpoint(app, "/api/confirmations/missed-dose")
    request = SessionRequest(patient_id="demo-ready-001", session_id=session_id)
    first = confirm(request)
    second = confirm(request)
    patient = app.state.service_for("demo-ready-001").repository.load()
    exact = [log for log in patient.dose_logs if log.medication_id == "plan_src_vitamin_d" and log.scheduled_at.isoformat() == "2026-08-01T13:00:00-04:00"]
    assert first == second
    assert len(exact) == 1 and exact[0].status == "taken_late"


def test_cancel_clears_pending_without_mutation(tmp_path):
    app, _, session_id = stage_missed_confirmation(tmp_path)
    before = app.state.service_for("demo-ready-001").repository.load().model_dump_json()
    result = endpoint(app, "/api/session/cancel")(SessionRequest(patient_id="demo-ready-001", session_id=session_id))
    after = app.state.service_for("demo-ready-001").repository.load().model_dump_json()
    assert result["message"] == "Okay. I did not change the dose record."
    assert before == after
    assert "pending_dose_followup" not in app.state.session_store._values[session_id]


def test_expired_and_cross_patient_confirmations_are_rejected_without_mutation(tmp_path):
    app, _, session_id = stage_missed_confirmation(tmp_path)
    before = app.state.service_for("demo-ready-001").repository.load().model_dump_json()
    confirm = endpoint(app, "/api/confirmations/missed-dose")
    with pytest.raises(HTTPException, match="another patient"):
        confirm(SessionRequest(patient_id="demo-unready-001", session_id=session_id))
    assert "pending_dose_followup" in app.state.session_store._values[session_id]
    app.state.session_store._values[session_id]["pending_dose_followup"]["expires_at"] = datetime.fromisoformat("2026-08-01T13:57:00-04:00")
    with pytest.raises(HTTPException, match="expired"):
        confirm(SessionRequest(patient_id="demo-ready-001", session_id=session_id))
    assert app.state.service_for("demo-ready-001").repository.load().model_dump_json() == before


def test_already_taken_confirmation_is_idempotent(tmp_path):
    app, _, session_id = stage_missed_confirmation(tmp_path)
    service = app.state.service_for("demo-ready-001")
    service.mark_exact_dose_taken("plan_src_vitamin_d", datetime.fromisoformat("2026-08-01T13:00:00-04:00"))
    result = endpoint(app, "/api/confirmations/missed-dose")(SessionRequest(patient_id="demo-ready-001", session_id=session_id))
    assert result["answer"] == "That dose was already recorded as taken."
    patient = service.repository.load()
    assert len([log for log in patient.dose_logs if log.medication_id == "plan_src_vitamin_d" and log.scheduled_at.isoformat() == "2026-08-01T13:00:00-04:00"]) == 1


def test_backend_failure_preserves_pending_and_patient_data(tmp_path, monkeypatch):
    import backend.app as backend_app

    app, _, session_id = stage_missed_confirmation(tmp_path)
    before = app.state.service_for("demo-ready-001").repository.load().model_dump_json()
    monkeypatch.setattr(backend_app, "handle_pending_reply", lambda *_args: (_ for _ in ()).throw(ValueError("temporary confirmation failure")))
    with pytest.raises(HTTPException, match="temporary confirmation failure"):
        endpoint(app, "/api/confirmations/missed-dose")(SessionRequest(patient_id="demo-ready-001", session_id=session_id))
    assert "pending_dose_followup" in app.state.session_store._values[session_id]
    assert app.state.service_for("demo-ready-001").repository.load().model_dump_json() == before
