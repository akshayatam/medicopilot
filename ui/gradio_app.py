from __future__ import annotations

import json

from gemma.client import OllamaClient, OllamaError
from gemma.intent_router import IntentRouter
from gemma.orchestrator import MedicationOrchestrator
from gemma.response_parser import IntentParseError
from medication.clock import FixedClock, SystemClock
from medication.health import ApplicationHealthService
from medication.patient_data_service import PatientDataService
from medication.runtime_service import RuntimeMedicationService, UNREADY_MESSAGE
from medication.schemas import UserInput


def new_session_state(patient_id: str) -> dict:
    return {"patient_id": patient_id, "conversation": [], "debug": {}, "pending_clarification": None}


def routing_failure_payload(patient_id: str, active_clock: str, error: Exception) -> tuple[str, dict]:
    response = "I could not route that request safely, so no medication action was performed. The local patient data remains available."
    return response, {"selected_patient_id": patient_id, "action": "ROUTING_ERROR", "tool_output": None,
                      "errors": [str(error)], "active_clock": active_clock,
                      "outcome": "routing_error",
                      "response_source": "deterministic_routing_error"}


def create_app(client: OllamaClient, patients_directory, demo_now: str | None = None):
    try:
        import gradio as gr
    except ImportError as exc:
        raise RuntimeError("Gradio is not installed. Run: pip install -r requirements.txt") from exc

    patients = PatientDataService(patients_directory)
    summaries = patients.list_available_patients()
    if not summaries: raise FileNotFoundError("No valid schema-v2 runtime patients were found.")
    choices = [(p.label, p.patient_id) for p in summaries]; initial = summaries[0].patient_id
    health_service = ApplicationHealthService(client, patients, demo_now)

    def service_for(patient_id: str):
        patient = patients.load_patient(patient_id)
        clock = FixedClock(demo_now) if demo_now else SystemClock(patient.source_record.patient.timezone)
        return RuntimeMedicationService(patients, patient_id, clock)

    def status_payload(patient_id: str):
        patient = patients.reload_patient(patient_id); ready = patient.import_summary
        return {"display_name": patient.source_record.patient.display_name, "age": patient.source_record.patient.age_at_dataset_reference_date,
                "preferred_language": patient.source_record.patient.preferred_language, "timezone": patient.source_record.patient.timezone,
                "readiness": "Ready" if ready.ready_for_medication_tracking else "Needs review",
                "confirmed_medication_count": len([m for m in patient.medication_plan.medications if m.included_in_daily_plan]),
                "allergy_status": patient.source_record.allergy_status, "blocking_issues": ready.blocking_issues, "warnings": ready.warnings}

    def today_payload(patient_id: str):
        try: return service_for(patient_id).list_today_medications()
        except ValueError as exc: return {"review_required": str(exc)}

    def history_payload(patient_id: str):
        try: return service_for(patient_id).show_medication_history()
        except ValueError as exc: return {"review_required": str(exc)}

    def review_payload(patient_id: str):
        patient = patients.reload_patient(patient_id); included = {sid for m in patient.medication_plan.medications for sid in m.source_medication_request_ids if m.included_in_daily_plan}
        flags = (patient.source_record.model_extra or {}).get("reconciliation_flags", [])
        return [{"id": m.get("id"), "raw_display": m.get("raw_display"), "fhir_status": m.get("fhir_status"), "current_use_status": m.get("current_use_status"), "validation_flags": m.get("validation_flags", []),
                 "reconciliation_flags": [f for f in flags if m.get("id") in f.get("related_medication_ids", [])], "included_in_plan": m.get("id") in included} for m in patient.source_record.medications]

    def select(patient_id: str):
        state = new_session_state(patient_id)
        return state, json.dumps(status_payload(patient_id), indent=2), json.dumps(today_payload(patient_id), indent=2), json.dumps(history_payload(patient_id), indent=2), json.dumps(review_payload(patient_id), indent=2), "", "{}"

    def ask(state: dict, question: str):
        patient_id = state.get("patient_id", initial); service = service_for(patient_id)
        orchestrator = MedicationOrchestrator(service, IntentRouter(client))
        try:
            result = orchestrator.handle(UserInput(text=question)); payload = result.as_dict(); answer = result.response
            payload.update(selected_patient_id=patient_id, readiness=patients.get_readiness(patient_id).model_dump(mode="json"),
                           selected_tool=result.action if result.tool_output is not None else None, repair_attempts=[])
        except (OllamaError, IntentParseError) as exc:
            answer, payload = routing_failure_payload(patient_id, service.clock.now().isoformat(), exc)
        state = dict(state); state["debug"] = payload; state["conversation"] = [*state.get("conversation", []), {"user": question, "assistant": answer}]
        return state, answer, json.dumps(payload, indent=2, ensure_ascii=False), json.dumps(today_payload(patient_id), indent=2), json.dumps(history_payload(patient_id), indent=2)

    def health(): return json.dumps(health_service.check(), indent=2)

    with gr.Blocks(title="MediCopilot") as demo:
        session = gr.State(new_session_state(initial))
        gr.Markdown("# MediCopilot\n**Runs locally.** Synthetic data only. This is medication-navigation support, not diagnosis, prescribing, interaction checking, or treatment advice.")
        patient = gr.Dropdown(choices=choices, value=initial, label="Patient")
        with gr.Tabs():
            with gr.Tab("Medication copilot"):
                status = gr.Code(json.dumps(status_payload(initial), indent=2), language="json", label="Patient status")
                today = gr.Code(json.dumps(today_payload(initial), indent=2), language="json", label="Today's confirmed medications")
                question = gr.Textbox(label="Ask the copilot", placeholder="What medicine comes next?")
                gr.Examples(["What medicine comes next?", "Did I take my heart tablet this morning?", "Mark my evening medicine as taken.", "What are the saved instructions for Metoprolol?"], inputs=question)
                response = gr.Markdown(); submit = gr.Button("Ask", variant="primary")
                history = gr.Code(json.dumps(history_payload(initial), indent=2), language="json", label="Recent app/synthetic dose history")
            with gr.Tab("Source review"):
                gr.Markdown("Read-only imported-order review. These records are never used as the daily medication plan.")
                review = gr.Code(json.dumps(review_payload(initial), indent=2), language="json", label="Source medications")
            with gr.Tab("System health"):
                health_box = gr.Code(health(), language="json", label="Local system health"); gr.Button("Refresh health").click(health, outputs=health_box)
        with gr.Accordion("Debug metadata", open=False): debug = gr.Code("{}", language="json")
        patient.change(select, inputs=patient, outputs=[session, status, today, history, review, response, debug])
        submit.click(ask, inputs=[session, question], outputs=[session, response, debug, today, history])
        question.submit(ask, inputs=[session, question], outputs=[session, response, debug, today, history])
    return demo
