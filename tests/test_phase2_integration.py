import json
import shutil
from pathlib import Path

import pytest
import app as cli_app
from config import Settings

from gemma.orchestrator import MedicationOrchestrator
from gemma.schemas import Action, Intent
from medication.clock import FixedClock
from medication.patient_data_service import PatientDataError, PatientDataService
from medication.runtime_service import RuntimeMedicationService, UNREADY_MESSAGE
from medication.schemas import UserInput
from medication.schemas import MedicationPlanItem
from ui.gradio_app import new_session_state
from ui.gradio_app import routing_failure_payload
from ui.gradio_app import APP_CSS, _accessibility_style, _dashboard_html, _simplify_response
from gemma.intent_router import IntentRouter


class Router:
    class Client: last_latency_ms = 1
    client = Client()
    def __init__(self, intent): self.intent = intent
    def route(self, _): return self.intent


@pytest.fixture
def runtime_patients(tmp_path):
    source = Path(__file__).parents[1] / "data" / "runtime_patients"
    target = tmp_path / "patients"; shutil.copytree(source, target)
    return PatientDataService(target)


def orchestrator(patients, patient_id, intent):
    service = RuntimeMedicationService(patients, patient_id, FixedClock("2026-08-01T10:00:00-04:00"))
    return MedicationOrchestrator(service, Router(intent)), service


def test_ready_patient_next_dose_uses_verified_plan(runtime_patients):
    app, _ = orchestrator(runtime_patients, "demo-ready-001", Intent(action=Action.FIND_NEXT_DOSE, confidence=1))
    result = app.handle(UserInput(text="What medicine comes next?"))
    assert "Vitamin D3" in result.response and "01:00 PM" in result.response
    assert "Example medicine" not in result.response


def test_alias_status_comes_only_from_dose_ledger(runtime_patients):
    app, _ = orchestrator(runtime_patients, "demo-ready-001", Intent(action=Action.CHECK_DOSE_STATUS, medication_reference="heart tablet", time_period="morning", confidence=1))
    result = app.handle(UserInput(text="Did I take my heart tablet this morning?"))
    assert "08:11 AM" in result.response
    assert result.medication_resolver_result["status"] == "MATCHED"
    assert result.medication_resolver_result["query"] == "heart tablet"


def test_ambiguous_mark_never_mutates(runtime_patients):
    before = runtime_patients.load_patient("demo-ready-001").model_dump_json()
    app, _ = orchestrator(runtime_patients, "demo-ready-001", Intent(action=Action.MARK_DOSE_TAKEN, medication_reference="tablet", confidence=1))
    result = app.handle(UserInput(text="Mark my tablet as taken."))
    after = runtime_patients.reload_patient("demo-ready-001").model_dump_json()
    assert "Which confirmed medication" in result.response
    assert result.medication_resolver_result["status"] == "AMBIGUOUS"
    assert before == after


def test_unready_patient_is_blocked(runtime_patients):
    app, _ = orchestrator(runtime_patients, "demo-unready-001", Intent(action=Action.FIND_NEXT_DOSE, confidence=1))
    result = app.handle(UserInput(text="What comes next?"))
    assert result.response == UNREADY_MESSAGE
    assert result.tool_output is None
    assert result.outcome == "patient_not_ready" and result.errors is None


def test_prn_has_no_invented_due_time(runtime_patients):
    patient = runtime_patients.load_patient("demo-ready-001")
    patient.medication_plan.medications.append(MedicationPlanItem.model_validate({"id":"plan_prn","source_medication_request_ids":["src_prn"],"patient_friendly_name":"Rescue inhaler","aliases":["as-needed medicine"],"schedule_type":"as_needed","reminder_schedule":[],"current_use_status":"confirmed_current","included_in_daily_plan":False,"reconciliation_status":"verified","verified_by":"synthetic_caregiver","verified_at":"2026-07-28T14:00:00-04:00","source":"synthetic_reconciliation_profile"}))
    runtime_patients.save_patient(patient)
    app, _ = orchestrator(runtime_patients, "demo-ready-001", Intent(action=Action.CHECK_DOSE_STATUS, medication_reference="as-needed medicine", confidence=1))
    result = app.handle(UserInput(text="When is my as-needed medicine due?"))
    assert "as-needed" in result.response and "no recurring due time" in result.response


def test_unsafe_bypasses_router_and_duplicate_mark_is_idempotent(runtime_patients):
    class ExplodingRouter(Router):
        def route(self, _): raise AssertionError("router must not run")
    service = RuntimeMedicationService(runtime_patients, "demo-ready-001", FixedClock("2026-08-01T10:00:00-04:00"))
    unsafe = MedicationOrchestrator(service, ExplodingRouter(None)).handle(UserInput(text="I missed yesterday. Should I take two today?"))
    assert "cannot recommend" in unsafe.response
    assert unsafe.active_clock == "2026-08-01T10:00:00-04:00"
    assert unsafe.outcome == "unsafe_request" and unsafe.errors is None
    app, _ = orchestrator(runtime_patients, "demo-ready-001", Intent(action=Action.MARK_DOSE_TAKEN, medication_reference="lunch tablet", confidence=1))
    first = app.handle(UserInput(text="Mark my lunch tablet as taken")); second = app.handle(UserInput(text="Mark my lunch tablet as taken"))
    assert first.tool_output["status"] == "taken" and second.tool_output["status"] == "already_taken"
    assert len(runtime_patients.reload_patient("demo-ready-001").dose_logs) == 6


def test_schema_versions_and_session_state_are_isolated(tmp_path):
    (tmp_path / "bad.runtime.json").write_text(json.dumps({"schema_version": "1.0"}))
    service = PatientDataService(tmp_path)
    assert "Unsupported patient schema" in service.validation_errors["bad.runtime.json"]
    a = new_session_state("a"); b = new_session_state("b"); a["conversation"].append("x")
    assert b["patient_id"] == "b" and b["conversation"] == []
    assert b["last_assistant_answer"] == "" and b["large_text"] is True
    assert b["high_contrast"] is True and b["simplified_mode"] is False


def test_dashboard_progress_uses_only_runtime_ledger_statuses():
    status = {"display_name": "Elena Rivera", "readiness": "Ready"}
    today = [
        {"name": "Medicine A", "strength": "10 mg", "scheduled_at": "2026-08-01T08:00:00-04:00", "status": "taken", "taken_at": "2026-08-01T08:11:00-04:00"},
        {"name": "Medicine B", "strength": "", "scheduled_at": "2026-08-01T13:00:00-04:00", "status": "due", "taken_at": ""},
        {"name": "Medicine C", "strength": "5 mg", "scheduled_at": "2026-08-01T20:00:00-04:00", "status": "unknown", "taken_at": ""},
    ]
    next_dose = {"status": "upcoming", "medication": "Medicine B", "scheduled_at": "2026-08-01T13:00:00-04:00"}
    rendered = _dashboard_html(status, today, next_dose, FixedClock("2026-08-01T10:00:00-04:00").now(), [])
    assert "1 of 3 doses completed" in rendered and "2 remaining" in rendered
    assert "33% complete" in rendered
    assert 'aria-valuenow="1"' in rendered and "Due now" in rendered
    assert "Taken at 8:11 AM" in rendered


def test_dashboard_date_and_future_statuses_match_active_demo_clock(runtime_patients):
    clock = FixedClock("2026-08-01T10:00:00-04:00")
    service = RuntimeMedicationService(runtime_patients, "demo-ready-001", clock)
    today = service.list_today_medications()
    by_time = {item["scheduled_at"][11:16]: item for item in today}

    assert by_time["08:00"]["status"] in {"taken", "taken_late"}
    assert by_time["13:00"]["status"] == "upcoming"
    assert by_time["20:00"]["status"] == "upcoming"

    status = {"display_name": "Elena Rivera", "readiness": "Ready"}
    rendered = _dashboard_html(status, today, service.find_next_dose(), clock.now(), [])
    assert "Saturday, August 1" in rendered
    assert "Friday, July 31" not in rendered
    assert "✓ Taken" in rendered
    assert rendered.count("○ Upcoming") == 3  # next-dose summary plus two future dose rows
    assert "! Missed" not in rendered


def test_dashboard_css_uses_stable_ids_responsive_columns_and_explicit_contrast():
    assert "#app-root.gradio-container" in APP_CSS
    assert "#dashboard-layout" in APP_CSS and "@media (max-width: 900px)" in APP_CSS
    assert ".safety-banner" in APP_CSS
    assert "--page-bg:#f6f8f7" in APP_CSS and "--text-primary:#17231c" in APP_CSS
    assert ".medicine-row { display:grid" in APP_CSS
    high_contrast = _accessibility_style(True, True)
    assert "background:#fff" in high_contrast and "color:#000" in high_contrast
    assert "filter:" not in high_contrast


def test_light_theme_reset_uses_semantic_palette_and_no_internal_selectors():
    semantic_classes = (
        "safety-banner", "patient-card", "next-dose-card", "progress-card",
        "medicine-list-card", "medicine-row", "quick-actions-card", "chat-card",
        "accessibility-card", "dashboard-select", "dashboard-input", "dashboard-chat",
        "dashboard-accordion", "primary-action", "secondary-action",
    )
    assert all(f".{name}" in APP_CSS for name in semantic_classes)
    assert "color-scheme:light" in APP_CSS
    assert "--body-text-color:var(--text-primary)" in APP_CSS
    assert "--input-background-fill:var(--card-bg)" in APP_CSS
    assert ".message" not in APP_CSS and ".svelte" not in APP_CSS
    assert "--ink:" not in APP_CSS and "--card:" not in APP_CSS


def test_unready_dashboard_does_not_present_source_orders_as_schedule():
    status = {"display_name": "Marcus Chen", "readiness": "Needs review"}
    rendered = _dashboard_html(status, {"review_required": UNREADY_MESSAGE}, {"status": "review_required"}, FixedClock("2026-08-01T10:00:00-04:00").now(), [])
    assert "Medication plan needs review" in rendered
    assert "source orders cannot be used for reminders" in rendered
    assert "0 of 0 doses completed" in rendered


def test_simplified_mode_preserves_safety_response_and_shortens_known_schedule():
    refusal = "I cannot recommend medication changes. Please contact a clinician or pharmacist."
    assert _simplify_response(refusal, {"outcome": "unsafe_request"}) == refusal
    payload = {"action": "LIST_TODAY_MEDICATIONS", "tool_output": [{"name": "Vitamin D3", "strength": "1000 IU", "scheduled_at": "2026-08-01T13:00:00-04:00"}]}
    assert _simplify_response("long answer", payload) == "• Vitamin D3 1000 IU at 1:00 PM."


def test_failed_repair_is_safe_and_does_not_mutate(runtime_patients):
    class InvalidClient:
        last_latency_ms = 3
        def __init__(self): self.values = iter(["not json", '{"action":"FIND_NEXT_DOSE","confidence":"high"}'])
        def chat(self, *_): return next(self.values)
    before = runtime_patients.load_patient("demo-ready-001").model_dump_json()
    service = RuntimeMedicationService(runtime_patients, "demo-ready-001", FixedClock("2026-08-01T10:00:00-04:00"))
    result = MedicationOrchestrator(service, IntentRouter(InvalidClient())).handle(UserInput(text="What comes next?"))
    assert result.action == "ROUTING_ERROR" and result.tool_output is None and result.repair_used
    assert result.raw_model_json == "not json" and result.repair_model_json
    assert runtime_patients.reload_patient("demo-ready-001").model_dump_json() == before


def test_gradio_safe_routing_error_object():
    response, debug = routing_failure_payload("p", "2026-08-01T10:00:00-04:00", ValueError("technical detail"))
    assert "technical detail" not in response
    assert debug["errors"] == ["technical detail"] and debug["tool_output"] is None


def test_fixed_clock_controls_today_without_cross_date_fallback(runtime_patients):
    on_demo_day = RuntimeMedicationService(runtime_patients, "demo-ready-001", FixedClock("2026-08-01T10:00:00-04:00"))
    today = on_demo_day.list_today_medications()
    assert today and all(item["scheduled_at"].startswith("2026-08-01") for item in today)
    no_data = RuntimeMedicationService(runtime_patients, "demo-ready-001", FixedClock("2026-08-02T10:00:00-04:00")).list_today_medications()
    assert no_data["status"] == "no_data" and no_data["date"] == "2026-08-02"
    assert "No other date was substituted" in no_data["message"]


def test_today_and_history_actions_use_runtime_ledger(runtime_patients):
    today_app, _ = orchestrator(runtime_patients, "demo-ready-001", Intent(action=Action.LIST_TODAY_MEDICATIONS, date_reference="today"))
    today = today_app.handle(UserInput(text="What medicines do I have today?"))
    assert "2026-07-31" not in today.response and "Metoprolol" in today.response
    history_app, _ = orchestrator(runtime_patients, "demo-ready-001", Intent(action=Action.SHOW_MEDICATION_HISTORY))
    history = history_app.handle(UserInput(text="Show my recent medication history."))
    assert "2026-07-31" in history.response and history.tool_executed == "SHOW_MEDICATION_HISTORY"
    assert "2026-08-01T13:00:00" not in history.response
    assert "2026-08-01T20:00:00" not in history.response


def test_demo_now_configuration_requires_timezone():
    assert Settings(demo_now="2026-08-01T10:00:00-04:00").demo_now.endswith("-04:00")
    with pytest.raises(ValueError, match="timezone offset"):
        Settings(demo_now="2026-08-01T10:00:00")


def test_cli_routing_failure_has_no_traceback(monkeypatch, capsys):
    class InvalidClient:
        model = "test"
        last_latency_ms = 1
        def __init__(self, *_): self.values = iter(["bad", "still bad"])
        def chat(self, *_): return next(self.values)
    monkeypatch.setattr(cli_app, "OllamaClient", InvalidClient)
    monkeypatch.setattr("sys.argv", ["app.py", "ask", "--patient", "demo-ready-001", "What comes next?"])
    cli_app.main()
    captured = capsys.readouterr()
    assert "Traceback" not in captured.out + captured.err
    payload = json.loads(captured.out)
    assert payload["action"] == "ROUTING_ERROR" and payload["tool_output"] is None
