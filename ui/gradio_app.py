from __future__ import annotations

import html
import json
from datetime import datetime
from typing import Any

from gemma.client import OllamaClient, OllamaError
from gemma.intent_router import IntentRouter
from gemma.orchestrator import MedicationOrchestrator
from gemma.response_parser import IntentParseError
from gemma.schemas import Action
from medication.clock import FixedClock, SystemClock
from medication.health import ApplicationHealthService
from medication.patient_data_service import PatientDataService
from medication.runtime_service import RuntimeMedicationService
from medication.schemas import UserInput

TAKEN_STATUSES = {"taken", "taken_late"}


def new_session_state(patient_id: str) -> dict:
    return {
        "patient_id": patient_id,
        "conversation": [],
        "last_assistant_answer": "",
        "simplified_mode": False,
        "large_text": True,
        "high_contrast": True,
        "debug_visible": False,
        "debug": {},
        "pending_clarification": None,
        "voice_transcript": "",
        "voice_transcript_approved": False,
        "pending_voice_action": None,
        "voice_language": "English",
        "last_transcription_result": None,
        "last_voice_error": None,
        "spoken_output_enabled": False,
    }


def routing_failure_payload(patient_id: str, active_clock: str, error: Exception) -> tuple[str, dict]:
    response = "I could not route that request safely, so no medication action was performed. The local patient data remains available."
    return response, {
        "selected_patient_id": patient_id,
        "action": "ROUTING_ERROR",
        "tool_output": None,
        "errors": [str(error)],
        "active_clock": active_clock,
        "outcome": "routing_error",
        "response_source": "deterministic_routing_error",
    }


def _display_time(value: str | None) -> str:
    if not value:
        return "Not recorded"
    return datetime.fromisoformat(value).strftime("%-I:%M %p")


def _chat_messages(conversation: list[dict[str, str]]) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for exchange in conversation:
        timestamp = exchange.get("timestamp")
        suffix = f"\n\n{_display_time(timestamp)}" if timestamp else ""
        if exchange.get("user"):
            messages.append({"role": "user", "content": exchange["user"] + suffix})
        if exchange.get("assistant"):
            messages.append({"role": "assistant", "content": exchange["assistant"] + suffix})
    return messages


def _simplify_response(answer: str, payload: dict[str, Any]) -> str:
    """Shorten presentation for known deterministic outputs without changing facts."""
    if payload.get("outcome") in {"unsafe_request", "patient_not_ready", "routing_error"}:
        return answer
    output = payload.get("tool_output")
    action = payload.get("action")
    if isinstance(output, dict) and output.get("message"):
        return str(output["message"])
    if action == "LIST_TODAY_MEDICATIONS" and isinstance(output, list):
        return "\n".join(
            f"• {item['name']} {item.get('strength', '')} at {_display_time(item.get('scheduled_at'))}."
            for item in output
        )
    if action == "SHOW_MEDICATION_HISTORY" and isinstance(output, list):
        return "\n".join(
            f"• {item['medication']}: {str(item['status']).replace('_', ' ')}."
            for item in output
        )
    return answer


def _status_label(status: str) -> str:
    labels = {
        "taken": "✓ Taken",
        "taken_late": "✓ Taken late",
        "due": "! Due now",
        "upcoming": "○ Upcoming",
        "missed": "! Missed",
        "skipped_by_user": "— Skipped (recorded by user)",
        "unknown": "? Status unknown",
    }
    return labels.get(status, status.replace("_", " ").title())


def _dashboard_html(
    status: dict, today: Any, next_dose: dict, local_now: datetime,
    prn: list[dict], purposes: dict[str, str] | None = None,
) -> str:
    purposes = purposes or {}
    ready = status["readiness"] == "Ready"
    readiness_text = "Medication plan verified" if ready else "Medication plan needs review"
    readiness_icon = "✓" if ready else "!"
    day = local_now.strftime("%A, %B %-d")
    doses = today if isinstance(today, list) else []
    completed = sum(item.get("status") in TAKEN_STATUSES for item in doses)
    total = len(doses)
    remaining = total - completed
    percent = round(100 * completed / total) if total else 0

    if ready and next_dose.get("status") == "upcoming":
        medication = html.escape(next_dose.get("medication", "Medication not available"))
        next_time = _display_time(next_dose.get("scheduled_at"))
        purpose = purposes.get(next_dose.get("medication", ""))
        purpose_line = f'<p class="purpose">Saved purpose: {html.escape(purpose)}</p>' if purpose else ""
        next_card = f"""
            <div class="next-card-heading"><p class="eyebrow">NEXT MEDICINE</p>
            <span class="status-pill status-pill-upcoming">○ Upcoming</span></div>
            <h2 class="next-medication-name">{medication}</h2>
            <p class="next-time next-medication-time">{next_time}</p>
            {purpose_line}
            <p class="status-text">According to the saved medication plan</p>"""
    elif ready:
        next_card = """
            <div class="next-card-heading"><p class="eyebrow">NEXT MEDICINE</p></div>
            <h2 class="next-medication-name">No upcoming dose</h2>
            <p class="status-text">According to the saved medication plan.</p>"""
    else:
        next_card = """
            <div class="next-card-heading"><p class="eyebrow">NEXT MEDICINE</p>
            <span class="status-pill status-pill-review">! Needs review</span></div>
            <h2 class="next-medication-name">Review required</h2>
            <p class="status-text">The source orders cannot be used for reminders until the medication plan is verified.</p>"""

    cards = []
    for item in doses:
        state = str(item.get("status", "unknown"))
        taken = f'<p class="taken-time">Taken at {_display_time(item.get("taken_at"))}</p>' if state in TAKEN_STATUSES else ""
        overdue = '<span class="badge overdue">Due now</span>' if state == "due" else ""
        purpose = purposes.get(item.get("name", ""))
        purpose_line = f'<p class="purpose">Saved purpose: {html.escape(purpose)}</p>' if purpose else ""
        cards.append(f"""
            <article class="medicine-card medicine-row status-{html.escape(state.replace('_', '-'))}">
              <div class="medicine-time"><strong>{_display_time(item.get('scheduled_at'))}</strong></div>
              <div class="medicine-details"><h3 class="medicine-name">{html.escape(item.get('name', 'Medication'))}</h3>
              <p class="strength medicine-strength">{html.escape(item.get('strength') or 'Strength not recorded')}</p>
              {purpose_line}</div>
              <div class="medicine-meta"><span class="status-pill">{_status_label(state)}</span>{overdue}{taken}</div>
            </article>""")
    if not cards:
        message = today.get("message", "No scheduled doses are stored for today.") if isinstance(today, dict) else "No scheduled doses are stored for today."
        cards.append(f'<div class="empty-state">{html.escape(message)}</div>')

    prn_cards = ""
    if prn:
        prn_items = []
        for item in prn:
            purpose_line = f'<p class="purpose">Saved purpose: {html.escape(item["purpose"])}</p>' if item.get("purpose") else ""
            prn_items.append(
                f'<article class="medicine-card medicine-row prn-card"><div><h3 class="medicine-name">{html.escape(item["name"])}</h3>'
                f'<p class="strength">{html.escape(item.get("strength") or "Strength not recorded")}</p>'
                f'{purpose_line}</div><div class="medicine-meta"><strong>As needed</strong>'
                '<span>No recurring due time</span></div></article>'
            )
        items = "".join(prn_items)
        prn_cards = f'<section class="prn-section"><h3>As-needed medicines</h3><p>Shown separately; no fixed reminder is created.</p>{items}</section>'

    return f"""
    <main class="med-dashboard" aria-label="Medication dashboard">
      <section class="summary-card patient-card">
        <div><p class="eyebrow">MEDICATION COPILOT</p><h1 class="patient-name">{html.escape(status['display_name'])}</h1>
        <p class="local-date patient-date">{day}</p></div>
        <div class="readiness {'ready' if ready else 'review'}" role="status">
          <strong>{readiness_icon} {readiness_text}</strong>
          <span>{'Ready for dose tracking' if ready else 'Dose tracking is unavailable'}</span>
        </div>
      </section>
      <section class="next-card next-dose-card">{next_card}</section>
      <section class="progress-card" aria-label="Today’s progress">
        <div class="section-heading"><div><p class="eyebrow">TODAY’S PROGRESS</p><h2>{completed} of {total} doses completed</h2></div></div>
        <div class="progress-track" role="progressbar" aria-valuemin="0" aria-valuemax="{total}" aria-valuenow="{completed}" aria-label="{completed} of {total} doses completed">
          <div class="progress-fill" style="width:{percent}%"></div>
        </div>
        <div class="progress-stats"><strong>{percent}% complete</strong><span>{remaining} remaining</span></div>
      </section>
      <section class="schedule-section medicine-list-card"><div class="section-heading"><div><p class="eyebrow">TODAY’S MEDICINES</p><h2>Your saved schedule</h2></div></div>
        {''.join(cards)}{prn_cards}
      </section>
    </main>"""


APP_CSS = """
#app-root.gradio-container {
  color-scheme:light;
  --page-bg:#f6f8f7; --card-bg:#ffffff; --card-bg-soft:#f4faf6;
  --text-primary:#17231c; --text-secondary:#4f6256; --text-muted:#6b7a70;
  --border:#d9e3dc; --green:#167a3f; --green-dark:#0f5a2e; --green-soft:#e9f6ed;
  --blue:#245f91; --blue-soft:#eaf3fb; --warning:#8a5a00; --warning-soft:#fff6dc;
  --danger:#9b2c2c; --danger-soft:#fdecec;
  --body-background-fill:var(--page-bg); --background-fill-primary:var(--card-bg);
  --background-fill-secondary:var(--card-bg-soft); --block-background-fill:var(--card-bg);
  --block-label-background-fill:var(--card-bg); --input-background-fill:var(--card-bg);
  --body-text-color:var(--text-primary); --body-text-color-subdued:var(--text-secondary);
  --block-label-text-color:var(--text-primary); --input-placeholder-color:#7a8b80;
  --border-color-primary:var(--border); --border-color-accent:var(--green);
  width:min(97vw,1560px) !important; max-width:1560px !important; min-height:100vh;
  padding:1.35rem 1.5rem 2.5rem !important; background:var(--page-bg) !important;
  color:var(--text-primary) !important;
  font-family:Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
}
html, body { background:#f6f8f7 !important; color-scheme:light; }
#app-root, #app-root * { box-sizing:border-box; }
#app-root, #app-root p, #app-root span, #app-root label, #app-root h1, #app-root h2,
#app-root h3, #app-root h4, #app-root h5, #app-root h6, #app-root strong, #app-root small {
  color:var(--text-primary); opacity:1;
}
.app-shell { gap:1.15rem; }
.safety-banner { padding:.78rem 1rem; border:1px solid #c9e5d1 !important; border-radius:14px;
  background:var(--green-soft) !important; color:var(--text-primary) !important; box-shadow:0 1px 2px rgb(20 40 30 / 5%); }
.safety-banner * { color:var(--text-primary) !important; opacity:1 !important; }
.safety-banner p { margin:0; }
#patient-controls { align-items:end; padding:.2rem 0 .35rem; }
#patient-controls button { max-width:260px; }
#dashboard-layout { align-items:flex-start; gap:1.35rem; }
#primary-dashboard, #support-column { min-width:0; }
#support-column { gap:1rem; }
.med-dashboard { display:grid; gap:1rem; font-size:17px; }
.patient-card,.next-dose-card,.progress-card,.medicine-list-card,.medicine-row,
.quick-actions-card,.chat-card,.accessibility-card,.dashboard-accordion {
  background:var(--card-bg) !important; color:var(--text-primary) !important;
  border:1px solid var(--border) !important;
}
.patient-card *,.next-dose-card *,.progress-card *,.medicine-list-card *,.medicine-row *,
.quick-actions-card *,.chat-card *,.accessibility-card * { color:inherit; opacity:1; }
.summary-card,.next-card,.progress-card,.schedule-section,.quick-actions-card,.chat-card,
.accessibility-card,.dashboard-accordion {
  border-radius:20px !important; box-shadow:0 8px 24px rgb(24 58 40 / 7%) !important;
}
.summary-card, .next-card, .progress-card, .schedule-section { padding:1.5rem; }
.summary-card, .section-heading { display:flex; justify-content:space-between; align-items:center; gap:1rem; }
.summary-card { min-height:136px; }
.patient-name { margin:.15rem 0 .25rem; color:var(--text-primary) !important; font-size:clamp(2rem,3vw,2.75rem); line-height:1.05; letter-spacing:-.035em; font-weight:760; }
.eyebrow { margin:0; color:var(--green-dark) !important; font-size:.78rem; font-weight:800; letter-spacing:.12em; }
.patient-date,.medicine-strength,.taken-time,.section-subtitle,.status-text,.purpose { color:var(--text-secondary) !important; opacity:1 !important; margin:.28rem 0; line-height:1.45; }
.readiness { min-width:235px; padding:.85rem 1rem; border-radius:14px; display:grid; gap:.2rem; }
.readiness.ready { color:var(--green-dark); background:var(--green-soft); border:1px solid #bddfc7; }
.readiness.review { color:var(--warning); background:var(--warning-soft); border:1px solid #ead49b; }
.readiness strong, .readiness span { color:inherit !important; }
.readiness span { font-size:.9rem; }
.next-dose-card { position:relative; overflow:hidden; min-height:270px; padding:1.8rem 2rem; border-color:#bddfc7 !important; background:var(--card-bg-soft) !important; }
.next-card-heading { display:flex; justify-content:space-between; align-items:center; gap:1rem; position:relative; z-index:1; }
.next-medication-name { position:relative; z-index:1; margin:1.15rem 0 .15rem; max-width:85%; color:var(--text-primary) !important; font-size:clamp(2.15rem,4vw,3.25rem); line-height:1.05; letter-spacing:-.035em; font-weight:760; }
.next-medication-time { position:relative; z-index:1; margin:.2rem 0 .65rem; color:var(--green-dark) !important; font-size:clamp(3.25rem,6vw,5rem); line-height:1; letter-spacing:-.045em; font-weight:800; }
.progress-card h2, .schedule-section h2 { margin:.25rem 0 0; font-size:1.45rem; letter-spacing:-.02em; }
.progress-track { height:14px; overflow:hidden; margin-top:1.25rem; border-radius:999px; background:#e5ece8; }
.progress-fill { height:100%; border-radius:inherit; background:linear-gradient(90deg,#168350,#32a76d); }
.progress-stats { display:flex; justify-content:space-between; gap:1rem; margin-top:.72rem; font-size:.92rem; }
.progress-stats strong { color:var(--green-dark) !important; }
.progress-stats span { color:var(--text-secondary) !important; }
.schedule-section { display:grid; gap:.7rem; }
.medicine-row { display:grid; grid-template-columns:100px minmax(0,1fr) auto; align-items:center; gap:1.15rem; padding:1.05rem 1rem; border-radius:15px; box-shadow:0 2px 8px rgb(23 55 38 / 4%); }
.medicine-name { margin:0; color:var(--text-primary) !important; font-size:1.22rem; line-height:1.25; font-weight:720; }
.medicine-time strong { color:var(--text-primary) !important; font-size:1.02rem; white-space:nowrap; }
.medicine-details { min-width:0; }
.medicine-meta { display:grid; justify-items:end; text-align:right; gap:.38rem; min-width:132px; }
.status-pill, .badge { display:inline-flex; align-items:center; width:max-content; border-radius:999px; padding:.3rem .68rem; font-size:.82rem; line-height:1.2; font-weight:800; border:1px solid transparent; white-space:nowrap; }
.status-upcoming .status-pill,.status-pill-upcoming { color:var(--blue) !important; background:var(--blue-soft); border-color:#c8dff3; }
.status-taken .status-pill,.status-taken-late .status-pill { color:var(--green-dark) !important; background:var(--green-soft); border-color:#bddfc7; }
.status-missed .status-pill,.status-due .status-pill,.badge.overdue { color:var(--warning) !important; background:var(--warning-soft); border-color:#ead49b; }
.status-unknown .status-pill { color:#51465e !important; background:#f2eef5; border-color:#d7ccdf; }
.status-pill-review { color:var(--warning) !important; background:var(--warning-soft); border-color:#ead49b; }
.taken-time { font-size:.84rem; }
.prn-section { display:grid; gap:.65rem; margin-top:.8rem; padding-top:1rem; border-top:1px solid var(--border); }
.prn-card { display:flex; justify-content:space-between; background:var(--card-bg-soft) !important; }
.empty-state { padding:1rem; border:1px dashed #8ca298; border-radius:12px; color:var(--text-primary); background:var(--card-bg-soft); }
.quick-actions-card,.chat-card { padding:1.15rem !important; }
.quick-actions { gap:.65rem; }
.quick-actions button, .ask-button button, #patient-controls button { min-height:54px !important; border-radius:13px !important; font-size:.98rem !important; font-weight:720 !important; box-shadow:none !important; }
.primary-action { color:#fff !important; background:var(--green) !important; border-color:var(--green) !important; }
.primary-action * { color:#fff !important; }
.primary-action:hover { background:var(--green-dark) !important; border-color:var(--green-dark) !important; }
.secondary-action { color:var(--text-primary) !important; background:var(--card-bg) !important; border:1px solid var(--border) !important; }
.secondary-action * { color:var(--text-primary) !important; }
.chat-card h2 { margin:.1rem 0 .8rem; font-size:1.28rem; }
.dashboard-input,.dashboard-chat,.dashboard-select,.dashboard-accordion,.developer-code { background:var(--card-bg) !important; color:var(--text-primary) !important; border-color:var(--border) !important; }
.dashboard-input *,.dashboard-select *,.dashboard-accordion * { color:var(--text-primary) !important; }
.dashboard-input *,.dashboard-select * { background-color:var(--card-bg) !important; }
#app-root input,#app-root textarea,#app-root select { background:#fff !important; color:var(--text-primary) !important; border:1px solid var(--border) !important; }
#app-root input::placeholder,#app-root textarea::placeholder { color:#7a8b80 !important; opacity:1 !important; }
#app-root [role="listbox"],#app-root [role="option"] { background:#fff !important; color:var(--text-primary) !important; }
.dashboard-chat * { color:var(--text-primary) !important; background-color:transparent !important; opacity:1 !important; }
.accessibility-card,.dashboard-accordion { overflow:hidden; }
.accessibility-card > button,.dashboard-accordion > button { min-height:58px; padding:0 1.1rem !important; color:var(--text-primary) !important; background:var(--card-bg) !important; font-weight:720 !important; }
.accessibility-card label { display:flex !important; align-items:center; min-height:52px; padding:.55rem .7rem !important; color:var(--text-primary) !important; border-top:1px solid var(--border); }
.accessibility-card input[type="checkbox"] { width:42px !important; height:24px !important; accent-color:var(--green); }
.future-voice { color:var(--text-secondary) !important; font-size:.9rem; opacity:1 !important; }
.developer-code,.developer-code * { color:var(--text-primary) !important; background:var(--card-bg) !important; opacity:1 !important; }
.large-text { font-size:110%; }
.standard-text { font-size:100%; }
#app-root button:focus-visible,#app-root input:focus-visible,#app-root textarea:focus-visible,#app-root [tabindex]:focus-visible { outline:3px solid var(--green) !important; outline-offset:2px; }
#app-root button:disabled,#app-root [aria-disabled="true"] { opacity:1 !important; color:#3f4c45 !important; background:#e1e6e3 !important; border-color:#9da9a2 !important; }
@media (max-width: 900px) {
  #dashboard-layout { flex-direction:column; }
  #primary-dashboard, #support-column { width:100%; flex-basis:auto !important; }
}
@media (max-width: 700px) {
  #app-root.gradio-container { width:100% !important; padding:.75rem .65rem 1.5rem !important; }
  .summary-card, .section-heading { align-items:flex-start; flex-direction:column; }
  .readiness { min-width:0; width:100%; }
  .next-dose-card { min-height:245px; padding:1.4rem; }
  .next-medication-name { max-width:100%; }
  .medicine-row { grid-template-columns:1fr auto; gap:.7rem; }
  .medicine-time { grid-column:1; grid-row:1; }
  .medicine-details { grid-column:1/-1; grid-row:2; }
  .medicine-meta { grid-column:2; grid-row:1; min-width:0; }
  #patient-controls { flex-direction:column; }
  #patient-controls button { width:100%; max-width:none; }
}
"""


def _accessibility_style(large_text: bool, high_contrast: bool) -> str:
    size = "110%" if large_text else "100%"
    if high_contrast:
        colors = """
        #app-root {
          --page-bg:#fff; --card-bg:#fff; --card-bg-soft:#fff;
          --text-primary:#000; --text-secondary:#222; --text-muted:#333;
          --border:#000; --green:#005f2f; --green-dark:#003d1f; --green-soft:#d9f2e2;
          --blue:#003f73; --blue-soft:#e2f1ff; --warning:#5b3900; --warning-soft:#ffedb3;
          --danger:#760000; --danger-soft:#ffe0e0;
          --body-background-fill:#fff; --background-fill-primary:#fff; --background-fill-secondary:#fff;
          --block-background-fill:#fff; --block-label-background-fill:#fff; --input-background-fill:#fff;
          --body-text-color:#000; --body-text-color-subdued:#222; --block-label-text-color:#000;
          --input-placeholder-color:#333; --border-color-primary:#000; --border-color-accent:#000;
        }
        #app-root .patient-card,#app-root .next-dose-card,#app-root .progress-card,
        #app-root .medicine-list-card,#app-root .medicine-row,#app-root .quick-actions-card,
        #app-root .chat-card,#app-root .accessibility-card,#app-root .dashboard-accordion {
          background:#fff !important; color:#000 !important; border-color:#000 !important;
        }
        #app-root .safety-banner { color:#000 !important; background:#fff !important; border-color:#000 !important; }
        #app-root button:disabled,#app-root [aria-disabled="true"] { color:#000 !important; background:#ddd !important; border-color:#000 !important; }
        """
    else:
        colors = ""
    return f"<style>#app-root.gradio-container {{ font-size: {size}; }}{colors}</style>"


def create_app(client: OllamaClient, patients_directory, demo_now: str | None = None):
    try:
        import gradio as gr
    except ImportError as exc:
        raise RuntimeError("Gradio is not installed. Run: pip install -r requirements.txt") from exc

    patients = PatientDataService(patients_directory)
    summaries = patients.list_available_patients()
    if not summaries:
        raise FileNotFoundError("No valid schema-v2 runtime patients were found.")
    choices = [(p.label, p.patient_id) for p in summaries]
    initial = summaries[0].patient_id
    health_service = ApplicationHealthService(client, patients, demo_now)
    from voice.audio import AudioValidationError, normalized_audio
    from voice.providers import GemmaAudioTranscriptionProvider
    from voice.schemas import PendingVoiceAction
    from voice.service import VoiceInteractionService
    voice_provider = GemmaAudioTranscriptionProvider(client.base_url, client.model, max(client.timeout, 90))

    def service_for(patient_id: str):
        patient_record = patients.load_patient(patient_id)
        clock = FixedClock(demo_now) if demo_now else SystemClock(patient_record.source_record.patient.timezone)
        return RuntimeMedicationService(patients, patient_id, clock)

    def status_payload(patient_id: str):
        patient_record = patients.reload_patient(patient_id)
        ready = patient_record.import_summary
        return {
            "display_name": patient_record.source_record.patient.display_name,
            "age": patient_record.source_record.patient.age_at_dataset_reference_date,
            "preferred_language": patient_record.source_record.patient.preferred_language,
            "timezone": patient_record.source_record.patient.timezone,
            "readiness": "Ready" if ready.ready_for_medication_tracking else "Needs review",
            "confirmed_medication_count": len([m for m in patient_record.medication_plan.medications if m.included_in_daily_plan]),
            "allergy_status": patient_record.source_record.allergy_status,
            "blocking_issues": ready.blocking_issues,
            "warnings": ready.warnings,
        }

    def today_payload(patient_id: str):
        try:
            return service_for(patient_id).list_today_medications()
        except ValueError as exc:
            return {"review_required": str(exc)}

    def next_payload(patient_id: str):
        try:
            return service_for(patient_id).find_next_dose()
        except ValueError as exc:
            return {"status": "review_required", "message": str(exc)}

    def history_payload(patient_id: str):
        try:
            return service_for(patient_id).show_medication_history()
        except ValueError as exc:
            return {"review_required": str(exc)}

    def prn_payload(patient_id: str):
        patient_record = patients.reload_patient(patient_id)
        return [
            {"name": med.patient_friendly_name, "strength": med.strength or "", "purpose": ", ".join(med.purpose_labels)}
            for med in patient_record.medication_plan.medications
            if med.current_use_status == "confirmed_current" and med.schedule_type == "as_needed"
        ]

    def dashboard(patient_id: str):
        service = service_for(patient_id)
        patient_record = patients.reload_patient(patient_id)
        purposes = {}
        for med in patient_record.medication_plan.medications:
            if not med.purpose_labels:
                continue
            purpose = ", ".join(med.purpose_labels)
            purposes[med.patient_friendly_name] = purpose
            purposes[f"{med.patient_friendly_name}{' ' + med.strength if med.strength else ''}"] = purpose
        return _dashboard_html(
            status_payload(patient_id), today_payload(patient_id), next_payload(patient_id),
            service.clock.now(), prn_payload(patient_id), purposes,
        )

    def review_payload(patient_id: str):
        patient_record = patients.reload_patient(patient_id)
        included = {sid for m in patient_record.medication_plan.medications for sid in m.source_medication_request_ids if m.included_in_daily_plan}
        flags = (patient_record.source_record.model_extra or {}).get("reconciliation_flags", [])
        return [{
            "id": m.get("id"), "raw_display": m.get("raw_display"), "fhir_status": m.get("fhir_status"),
            "current_use_status": m.get("current_use_status"), "validation_flags": m.get("validation_flags", []),
            "reconciliation_flags": [f for f in flags if m.get("id") in f.get("related_medication_ids", [])],
            "included_in_plan": m.get("id") in included,
        } for m in patient_record.source_record.medications]

    def debug_text(state: dict) -> str:
        return json.dumps(state.get("debug", {}), indent=2, ensure_ascii=False)

    def append_answer(state: dict, user_text: str, answer: str, payload: dict) -> dict:
        state = dict(state)
        if state.get("simplified_mode"):
            answer = _simplify_response(answer, payload)
        timestamp = payload.get("active_clock")
        state["debug"] = payload
        state["last_assistant_answer"] = answer
        state["conversation"] = [*state.get("conversation", []), {"user": user_text, "assistant": answer, "timestamp": timestamp}]
        return state

    def select(patient_id: str, simplified: bool, large_text: bool, high_contrast: bool):
        state = new_session_state(patient_id)
        state.update(simplified_mode=simplified, large_text=large_text, high_contrast=high_contrast)
        return state, dashboard(patient_id), [], json.dumps(review_payload(patient_id), indent=2), "{}", "", "", gr.update(visible=False), gr.update(visible=False), ""

    def transcribe_voice(state: dict, audio_path: str | None, language: str):
        state = dict(state)
        state.update(voice_transcript="", voice_transcript_approved=False, pending_voice_action=None, voice_language=language, last_voice_error=None)
        if not audio_path:
            state["last_voice_error"] = "No audio recording was provided."
            return state, "", "No audio recording was provided.", gr.update(visible=False), gr.update(visible=False)
        try:
            with normalized_audio(audio_path) as (normalized, _metadata):
                result = voice_provider.transcribe(normalized, language)
            state["last_transcription_result"] = result.model_dump(mode="json", exclude={"text"})
            if not result.success:
                message = result.warning or "The recording could not be transcribed locally."
                state["last_voice_error"] = message
                return state, "", message, gr.update(visible=False), gr.update(visible=False)
            state["voice_transcript"] = result.text
            return state, result.text, "I heard the text below. Review or edit it before submitting.", gr.update(visible=True), gr.update(visible=False)
        except (AudioValidationError, ValueError) as exc:
            state["last_voice_error"] = str(exc)
            return state, "", str(exc), gr.update(visible=False), gr.update(visible=False)

    def cancel_voice(state: dict):
        state = dict(state)
        state.update(voice_transcript="", voice_transcript_approved=False, pending_voice_action=None, last_voice_error=None)
        return state, None, "", "Voice request cancelled.", gr.update(visible=False), gr.update(visible=False), ""

    def submit_voice(state: dict, transcript: str):
        state = dict(state)
        patient_id = state.get("patient_id", initial)
        transcript = (transcript or "").strip()
        state["voice_transcript"] = transcript
        state["voice_transcript_approved"] = True
        interaction = VoiceInteractionService(service_for(patient_id), IntentRouter(client))
        try:
            result, pending = interaction.submit_transcript(transcript)
            if pending:
                state["pending_voice_action"] = pending.model_dump(mode="json")
                when = _display_time(pending.scheduled_at.isoformat())
                prompt = f"Record {pending.medication_display}, scheduled at {when} on {pending.scheduled_at.date().isoformat()}, as taken?"
                return state, _chat_messages(state.get("conversation", [])), debug_text(state), dashboard(patient_id), prompt, gr.update(visible=True), "Transcript approved. Confirm the exact proposed action below."
            payload = result.as_dict()
            payload.update(selected_patient_id=patient_id, voice_input=True, transcription_metadata=state.get("last_transcription_result"))
            state = append_answer(state, transcript, result.response, payload)
            state.update(voice_transcript="", pending_voice_action=None)
            return state, _chat_messages(state["conversation"]), debug_text(state), dashboard(patient_id), "", gr.update(visible=False), "Transcript submitted."
        except (OllamaError, IntentParseError, ValueError) as exc:
            state["pending_voice_action"] = None
            return state, _chat_messages(state.get("conversation", [])), debug_text(state), dashboard(patient_id), "", gr.update(visible=False), str(exc)

    def confirm_voice(state: dict):
        state = dict(state)
        patient_id = state.get("patient_id", initial)
        raw = state.get("pending_voice_action")
        if not raw:
            return state, _chat_messages(state.get("conversation", [])), debug_text(state), dashboard(patient_id), "No pending voice action remains.", gr.update(visible=False), ""
        try:
            pending = PendingVoiceAction.model_validate(raw)
            output = VoiceInteractionService(service_for(patient_id), IntentRouter(client)).confirm(pending)
            payload = {"selected_patient_id": patient_id, "action": pending.action, "selected_tool": pending.action, "tool_output": output, "active_clock": service_for(patient_id).clock.now().isoformat(), "outcome": "success", "response_source": "deterministic_runtime_service", "voice_input": True, "errors": None}
            state = append_answer(state, pending.transcript, output["message"], payload)
            state.update(pending_voice_action=None, voice_transcript="", voice_transcript_approved=False)
            return state, _chat_messages(state["conversation"]), debug_text(state), dashboard(patient_id), "Dose recorded through the existing runtime service.", gr.update(visible=False), ""
        except ValueError as exc:
            state["pending_voice_action"] = None
            return state, _chat_messages(state.get("conversation", [])), debug_text(state), dashboard(patient_id), str(exc), gr.update(visible=False), ""

    def ask(state: dict, question: str):
        question = (question or "").strip()
        if not question:
            return state, _chat_messages(state.get("conversation", [])), debug_text(state), dashboard(state.get("patient_id", initial)), ""
        patient_id = state.get("patient_id", initial)
        service = service_for(patient_id)
        orchestrator = MedicationOrchestrator(service, IntentRouter(client))
        try:
            result = orchestrator.handle(UserInput(text=question))
            payload = result.as_dict()
            answer = result.response
            payload.update(
                selected_patient_id=patient_id,
                readiness=patients.get_readiness(patient_id).model_dump(mode="json"),
                selected_tool=result.action if result.tool_output is not None else None,
                repair_attempts=[],
            )
        except (OllamaError, IntentParseError) as exc:
            answer, payload = routing_failure_payload(patient_id, service.clock.now().isoformat(), exc)
        state = append_answer(state, question, answer, payload)
        return state, _chat_messages(state["conversation"]), debug_text(state), dashboard(patient_id), ""

    def direct_action(state: dict, action: str):
        patient_id = state.get("patient_id", initial)
        service = service_for(patient_id)
        labels = {
            "today": "Show today's medicines",
            "next": "What comes next?",
            "history": "Show medication history",
            "mark_next": "Mark next dose taken",
        }
        try:
            if action == "today":
                output = service.list_today_medications()
                answer = MedicationOrchestrator._format(Action.LIST_TODAY_MEDICATIONS, output)
                action_name = "LIST_TODAY_MEDICATIONS"
            elif action == "next":
                output = service.find_next_dose()
                answer = output["message"]
                action_name = "FIND_NEXT_DOSE"
            elif action == "history":
                output = service.show_medication_history()
                answer = MedicationOrchestrator._format(Action.SHOW_MEDICATION_HISTORY, output)
                action_name = "SHOW_MEDICATION_HISTORY"
            else:
                upcoming = service.find_next_dose()
                if upcoming.get("status") != "upcoming":
                    output = upcoming
                else:
                    output = service.mark_dose_taken(upcoming["medication"])
                answer = output["message"]
                action_name = "MARK_DOSE_TAKEN"
            payload = {
                "selected_patient_id": patient_id, "action": action_name, "selected_tool": action_name,
                "tool_output": output, "active_clock": service.clock.now().isoformat(), "outcome": "success",
                "response_source": "deterministic_direct_action", "intent": None, "medication_resolver_result": None,
                "model_latency_ms": None, "errors": None,
            }
        except ValueError as exc:
            answer = str(exc)
            payload = {
                "selected_patient_id": patient_id, "action": action.upper(), "selected_tool": None,
                "tool_output": None, "active_clock": service.clock.now().isoformat(), "outcome": "patient_not_ready",
                "response_source": "deterministic_runtime_service", "errors": None,
            }
        state = append_answer(state, labels[action], answer, payload)
        return state, _chat_messages(state["conversation"]), debug_text(state), dashboard(patient_id)

    def repeat(state: dict):
        answer = state.get("last_assistant_answer") or "There is no previous answer to repeat yet."
        payload = {"action": "REPEAT_LAST_ANSWER", "active_clock": service_for(state.get("patient_id", initial)).clock.now().isoformat()}
        state = append_answer(state, "Repeat last answer", answer, payload)
        return state, _chat_messages(state["conversation"]), debug_text(state)

    def update_preferences(state: dict, simplified: bool, large_text: bool, high_contrast: bool):
        state = dict(state)
        state.update(simplified_mode=simplified, large_text=large_text, high_contrast=high_contrast)
        return state, _accessibility_style(large_text, high_contrast)

    def health():
        return json.dumps(health_service.check(), indent=2)

    with gr.Blocks(title="Medication Copilot", elem_id="app-root", elem_classes=["large-text", "app-shell"]) as demo:
        session = gr.State(new_session_state(initial))
        gr.HTML(f"<style>{APP_CSS}</style>", container=False)
        accessibility_style = gr.HTML(_accessibility_style(True, True), container=False)
        gr.Markdown("**Synthetic data only · Runs locally** — Medication navigation and adherence support, not diagnosis, prescribing, interaction checking, or treatment advice.", elem_id="safety-banner", elem_classes="safety-banner")
        with gr.Row(elem_id="patient-controls"):
            patient = gr.Dropdown(choices=choices, value=initial, label="Choose a patient", scale=2, elem_classes="dashboard-select")
            refresh = gr.Button("↻ Refresh dashboard", scale=1, elem_classes="secondary-action")

        with gr.Row(elem_id="dashboard-layout"):
            with gr.Column(scale=7, min_width=520, elem_id="primary-dashboard"):
                dashboard_box = gr.HTML(dashboard(initial), elem_classes="dashboard-content")
            with gr.Column(scale=5, min_width=380, elem_id="support-column"):
                with gr.Group(elem_classes="quick-actions-card"):
                    gr.Markdown("## Quick actions")
                    with gr.Row(elem_classes="quick-actions"):
                        mark_next = gr.Button("✓ Mark next dose taken", variant="primary", elem_classes="primary-action")
                        next_button = gr.Button("What comes next?", elem_classes="secondary-action")
                    with gr.Row(elem_classes="quick-actions"):
                        today_button = gr.Button("Show today’s medicines", elem_classes="secondary-action")
                        repeat_button = gr.Button("Repeat last answer", elem_classes="secondary-action")
                        history_button = gr.Button("History", elem_classes="secondary-action")

                with gr.Group(elem_classes="chat-card"):
                    gr.Markdown("## Ask Medication Copilot")
                    with gr.Row():
                        question = gr.Textbox(label="Medication question", placeholder="For example: Did I take my heart tablet this morning?", scale=4, elem_classes="dashboard-input")
                        submit = gr.Button("Ask", variant="primary", scale=1, elem_classes=["ask-button", "primary-action"])
                    conversation = gr.Chatbot(label="Conversation", height=280, elem_classes="dashboard-chat")
                    gr.Markdown("### Voice input")
                    gr.Markdown("Voice is processed locally and is not saved by default. Recording limit: 30 seconds.")
                    voice_language = gr.Dropdown(["English"], value="English", label="Voice language")
                    voice_audio = gr.Audio(sources=["microphone", "upload"], type="filepath", label="Record a voice question or upload audio")
                    voice_status = gr.Markdown("Record or upload audio; nothing is submitted automatically.")
                    transcript = gr.Textbox(label="I heard — review and edit before submitting", interactive=True)
                    with gr.Row(visible=False) as transcript_controls:
                        submit_transcript = gr.Button("Submit transcript", variant="primary", elem_classes="primary-action")
                        record_again = gr.Button("Record again", elem_classes="secondary-action")
                        cancel_transcript = gr.Button("Cancel", elem_classes="secondary-action")
                    with gr.Group(visible=False) as confirmation_controls:
                        confirmation_text = gr.Markdown("")
                        with gr.Row():
                            confirm_voice_action = gr.Button("Confirm and record", variant="primary", elem_classes="primary-action")
                            cancel_voice_action = gr.Button("Cancel proposed action", elem_classes="secondary-action")

                with gr.Accordion("Accessibility settings", open=False, elem_classes=["accessibility-card", "dashboard-accordion"]):
                    simplified = gr.Checkbox(False, label="Simplified language")
                    large_text = gr.Checkbox(True, label="Large text")
                    high_contrast = gr.Checkbox(True, label="High contrast")
                    gr.Markdown("Spoken output (TTS) is not implemented. Repeat last answer remains text-only.", elem_classes="future-voice")

                with gr.Accordion("Source record review (not used for reminders)", open=False, elem_classes="dashboard-accordion"):
                    gr.Markdown("Read-only imported-order review. These records are never used as the daily medication plan.")
                    review = gr.Code(json.dumps(review_payload(initial), indent=2), language="json", label="Source medications", elem_classes="developer-code")
                with gr.Accordion("Developer debug information", open=False, elem_classes="dashboard-accordion"):
                    gr.Markdown("Routing metadata only. Model chain-of-thought is never requested or displayed.")
                    debug = gr.Code("{}", language="json", label="Intent, resolver, tool output, latency, and clock", elem_classes="developer-code")
                with gr.Accordion("System health", open=False, elem_classes="dashboard-accordion"):
                    health_box = gr.Code(health(), language="json", label="Local system health", elem_classes="developer-code")
                    gr.Button("Refresh system health", elem_classes="secondary-action").click(health, outputs=health_box)

        patient.change(select, inputs=[patient, simplified, large_text, high_contrast], outputs=[session, dashboard_box, conversation, review, debug, question, transcript, transcript_controls, confirmation_controls, confirmation_text])
        refresh.click(lambda state: dashboard(state.get("patient_id", initial)), inputs=session, outputs=dashboard_box)
        submit.click(ask, inputs=[session, question], outputs=[session, conversation, debug, dashboard_box, question])
        question.submit(ask, inputs=[session, question], outputs=[session, conversation, debug, dashboard_box, question])
        today_button.click(lambda state: direct_action(state, "today"), inputs=session, outputs=[session, conversation, debug, dashboard_box])
        next_button.click(lambda state: direct_action(state, "next"), inputs=session, outputs=[session, conversation, debug, dashboard_box])
        history_button.click(lambda state: direct_action(state, "history"), inputs=session, outputs=[session, conversation, debug, dashboard_box])
        mark_next.click(lambda state: direct_action(state, "mark_next"), inputs=session, outputs=[session, conversation, debug, dashboard_box])
        repeat_button.click(repeat, inputs=session, outputs=[session, conversation, debug])
        voice_audio.change(transcribe_voice, inputs=[session, voice_audio, voice_language], outputs=[session, transcript, voice_status, transcript_controls, confirmation_controls])
        submit_transcript.click(submit_voice, inputs=[session, transcript], outputs=[session, conversation, debug, dashboard_box, confirmation_text, confirmation_controls, voice_status])
        confirm_voice_action.click(confirm_voice, inputs=session, outputs=[session, conversation, debug, dashboard_box, voice_status, confirmation_controls, confirmation_text])
        cancel_transcript.click(cancel_voice, inputs=session, outputs=[session, voice_audio, transcript, voice_status, transcript_controls, confirmation_controls, confirmation_text])
        record_again.click(cancel_voice, inputs=session, outputs=[session, voice_audio, transcript, voice_status, transcript_controls, confirmation_controls, confirmation_text])
        cancel_voice_action.click(cancel_voice, inputs=session, outputs=[session, voice_audio, transcript, voice_status, transcript_controls, confirmation_controls, confirmation_text])
        for control in (simplified, large_text, high_contrast):
            control.change(update_preferences, inputs=[session, simplified, large_text, high_contrast], outputs=[session, accessibility_style])
    return demo
