from datetime import datetime
from pathlib import Path
import shutil

import pytest
from pydantic import ValidationError

from gemma.orchestrator import MedicationOrchestrator
from gemma.schemas import Action, Intent
from medication.clock import FixedClock
from medication.dose_status import DoseStatusPolicy, calculate_effective_dose_status
from medication.followup import PendingDoseFollowup, handle_pending_reply
from medication.patient_data_service import PatientDataService
from medication.runtime_service import RuntimeMedicationService, UNREADY_MESSAGE
from medication.schemas import DoseLogRecord, UserInput
from scripts.demo_management import reset_demo
from ui.gradio_app import _dashboard_html
from voice.service import VoiceInteractionService


def dose(status="upcoming", scheduled="2026-08-01T13:00:00-04:00", taken_at=None):
    return DoseLogRecord(
        id="dose-1", medication_id="med-1", scheduled_at=scheduled,
        status=status, taken_at=taken_at, source="app_event",
    )


@pytest.mark.parametrize(("now", "expected"), [
    ("2026-08-01T12:45:00-04:00", "upcoming"),
    ("2026-08-01T13:00:00-04:00", "due"),
    ("2026-08-01T13:10:00-04:00", "due"),
    ("2026-08-01T13:31:00-04:00", "missed"),
])
def test_effective_status_clock_boundaries(now, expected):
    assert calculate_effective_dose_status(dose(), datetime.fromisoformat(now), DoseStatusPolicy()) == expected


def test_recorded_and_explicit_statuses_remain_authoritative():
    policy = DoseStatusPolicy()
    now = datetime.fromisoformat("2026-08-01T14:00:00-04:00")
    assert calculate_effective_dose_status(dose("taken", taken_at="2026-08-01T13:05:00-04:00"), now, policy) == "taken"
    assert calculate_effective_dose_status(dose("taken_late", taken_at="2026-08-01T13:45:00-04:00"), now, policy) == "taken_late"
    assert calculate_effective_dose_status(dose("skipped_by_user"), now, policy) == "skipped_by_user"
    assert calculate_effective_dose_status(dose("unknown"), now, policy) == "unknown"


def test_effective_status_requires_aware_timestamps():
    with pytest.raises(ValueError, match="timezone-aware current"):
        calculate_effective_dose_status(dose(), datetime(2026, 8, 1, 13), DoseStatusPolicy())
    naive_dose = dose(scheduled="2026-08-01T13:00:00")
    with pytest.raises(ValueError, match="timezone-aware scheduled"):
        calculate_effective_dose_status(naive_dose, datetime.fromisoformat("2026-08-01T13:00:00-04:00"), DoseStatusPolicy())
    with pytest.raises(ValidationError):
        DoseStatusPolicy(due_window_minutes=-1)
    with pytest.raises(ValidationError, match="at least the due window"):
        DoseStatusPolicy(due_window_minutes=15, missed_after_minutes=10)


def test_effective_status_compares_timezone_aware_instants():
    # 17:10 UTC is the same instant as 1:10 PM in New York.
    assert calculate_effective_dose_status(
        dose(), datetime.fromisoformat("2026-08-01T17:10:00+00:00"), DoseStatusPolicy()
    ) == "due"


@pytest.fixture
def patients(tmp_path):
    target = tmp_path / "patients"
    shutil.copytree(Path(__file__).parents[1] / "data" / "runtime_patients", target)
    return PatientDataService(target)


def service(patients, now):
    return RuntimeMedicationService(patients, "demo-ready-001", FixedClock(now))


def test_cross_surface_statuses_agree_after_missed_threshold(patients):
    runtime = service(patients, "2026-08-01T13:58:00-04:00")
    today = runtime.list_today_medications()
    vitamin = next(item for item in today if item["name"] == "Vitamin D3")
    assert vitamin["stored_status"] == "upcoming" and vitamin["effective_status"] == "missed"
    assert runtime.check_dose_status("lunch tablet")["status"] == "missed"
    missed = runtime.check_missed_doses()
    assert [item["name"] for item in missed["doses"]] == ["Vitamin D3"]
    assert runtime.find_next_dose()["medication"] == "Metformin 500 mg"
    assert any(item["medication"].startswith("Vitamin D3") and item["status"] == "missed" for item in runtime.show_medication_history())
    rendered = _dashboard_html(
        {"display_name": "Elena Rivera", "readiness": "Ready"}, today,
        runtime.find_next_dose(), runtime.clock.now(), [],
    )
    assert "! Missed" in rendered and "1 of 3 scheduled doses recorded as taken" in rendered
    assert "1 missed or overdue" in rendered and "1 remaining" in rendered


def test_next_dose_uses_same_due_policy(patients):
    before = service(patients, "2026-08-01T12:45:00-04:00")
    due = service(patients, "2026-08-01T13:10:00-04:00")
    assert before.find_next_dose()["status"] == "upcoming"
    assert due.find_next_dose()["status"] == "due"
    assert due.find_next_dose()["medication"] == "Vitamin D3 1000 IU"


class Router:
    class Client:
        last_latency_ms = 1
    client = Client()
    def __init__(self, intent): self.intent = intent
    def route(self, _text): return self.intent


def test_dedicated_missed_action_and_record_based_wording(patients):
    runtime = service(patients, "2026-08-01T13:58:00-04:00")
    result = MedicationOrchestrator(runtime, Router(Intent(action=Action.CHECK_MISSED_DOSES))).handle(
        UserInput(text="Have I missed any medicine?")
    )
    assert result.action == "CHECK_MISSED_DOSES"
    assert result.response == "Vitamin D3 1000 IU was scheduled for 1:00 PM and is not recorded as taken. Did you take it? I can record that dose as taken."
    assert result.dose_status_policy == {"due_window_minutes": 15, "missed_after_minutes": 30}


def test_no_missed_multiple_missed_and_unready_outcomes(patients):
    assert service(patients, "2026-08-01T12:45:00-04:00").check_missed_doses()["status"] == "no_missed_doses"
    multiple = service(patients, "2026-08-01T20:31:00-04:00").check_missed_doses()
    assert len(multiple["doses"]) == 2 and "Which medicine" in multiple["message"]
    unready = RuntimeMedicationService(patients, "demo-unready-001", FixedClock("2026-08-01T13:58:00-04:00"))
    with pytest.raises(ValueError, match=UNREADY_MESSAGE):
        unready.check_missed_doses()


def test_exact_pending_yes_no_expiry_and_bare_affirmative(patients):
    runtime = service(patients, "2026-08-01T13:58:00-04:00")
    missed = runtime.check_missed_doses()["doses"][0]
    pending = PendingDoseFollowup.from_missed_dose(runtime.patient_id, runtime.patient_data_version(), missed, runtime.clock.now())
    before = runtime.repository.load().model_dump_json()
    assert handle_pending_reply(runtime, None, "yes")["status"] == "no_pending_action"
    assert handle_pending_reply(runtime, pending, "no")["status"] == "cancelled"
    assert runtime.repository.load().model_dump_json() == before
    output = handle_pending_reply(runtime, pending, "yeah")
    assert output["status"] == "taken_late" and "Vitamin D3 1000 IU" in output["message"]
    assert handle_pending_reply(runtime, pending, "yes")["status"] == "already_taken"
    expired = pending.model_copy(update={"expires_at": datetime.fromisoformat("2026-08-01T13:57:00-04:00")})
    with pytest.raises(ValueError, match="expired"):
        handle_pending_reply(runtime, expired, "yes")


def test_multiple_missed_doses_do_not_create_one_pending_action(patients):
    runtime = service(patients, "2026-08-01T20:31:00-04:00")
    result = runtime.check_missed_doses()
    assert len(result["doses"]) == 2
    assert handle_pending_reply(runtime, None, "yes")["status"] == "no_pending_action"


def test_approved_voice_transcript_uses_same_missed_dose_flow(patients):
    runtime = service(patients, "2026-08-01T13:58:00-04:00")
    result, voice_pending = VoiceInteractionService(
        runtime, Router(Intent(action=Action.CHECK_MISSED_DOSES))
    ).submit_transcript("Have I missed any medicine?")
    assert voice_pending is None
    assert result.action == "CHECK_MISSED_DOSES"
    assert result.tool_output["doses"][0]["name"] == "Vitamin D3"


def test_demo_reset_invalidates_pending_confirmation(patients):
    runtime = service(patients, "2026-08-01T13:58:00-04:00")
    missed = runtime.check_missed_doses()["doses"][0]
    pending = PendingDoseFollowup.from_missed_dose(
        runtime.patient_id, runtime.patient_data_version(), missed, runtime.clock.now()
    )
    reset_demo(patients.directory)
    with pytest.raises(ValueError, match="patient data changed"):
        handle_pending_reply(runtime, pending, "yes")
