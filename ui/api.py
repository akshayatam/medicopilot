from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from gemma.client import OllamaClient, OllamaError
from gemma.intent_router import IntentRouter
from gemma.orchestrator import MedicationOrchestrator
from gemma.response_parser import IntentParseError
from gemma.schemas import Action
from medication.clock import FixedClock, SystemClock
from medication.dose_status import DoseStatusPolicy
from medication.health import ApplicationHealthService
from medication.patient_data_service import PatientDataError, PatientDataService
from medication.runtime_service import RuntimeMedicationService, UNREADY_MESSAGE
from medication.schemas import UserInput


class AskRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2_000)
    simplified: bool = False


class MarkTakenRequest(BaseModel):
    confirmed: Literal[True]


def _simplify_response(answer: str, payload: dict[str, Any]) -> str:
    if payload.get("outcome") in {"unsafe_request", "patient_not_ready", "routing_error"}:
        return answer
    output = payload.get("tool_output")
    if isinstance(output, dict) and output.get("message"):
        return str(output["message"])
    if payload.get("action") == "LIST_TODAY_MEDICATIONS" and isinstance(output, list):
        return "\n".join(
            f"• {item['name']} {item.get('strength', '')} at {_display_time(item['scheduled_at'])}."
            for item in output
        )
    if payload.get("action") == "SHOW_MEDICATION_HISTORY" and isinstance(output, list):
        return "\n".join(
            f"• {item['medication']}: {str(item['status']).replace('_', ' ')}."
            for item in output
        )
    return answer


def _display_time(value: str) -> str:
    return datetime.fromisoformat(value).strftime("%I:%M %p").lstrip("0")


def _dose_presentation_labels(patient: Any) -> dict[str, dict[str, Any]]:
    """Expose verified schedule labels for each stored dose so the interface never derives them.

    Only fields already carried by the verified plan are returned. A dose whose scheduled clock
    time has no matching verified reminder entry receives null labels rather than an inferred one.
    """
    confirmed = {
        item.id: item
        for item in patient.medication_plan.medications
        if item.current_use_status == "confirmed_current"
        and item.included_in_daily_plan
        and item.reconciliation_status == "verified"
    }
    labels: dict[str, dict[str, Any]] = {}
    for log in patient.dose_logs:
        medication = confirmed.get(log.medication_id)
        if medication is None:
            continue
        clock_time = log.scheduled_at.strftime("%H:%M")
        entry = next((slot for slot in medication.reminder_schedule if slot.time == clock_time), None)
        labels[log.id] = {
            "period": entry.period if entry else None,
            "meal_context": entry.meal_context if entry else None,
            "instruction": medication.source_instruction,
            "purpose": ", ".join(medication.purpose_labels),
        }
    return labels


def create_api(
    client: OllamaClient,
    patients_directory: str | Path,
    demo_now: str | None = None,
    frontend_dist: str | Path | None = None,
    dose_status_policy: DoseStatusPolicy | None = None,
) -> FastAPI:
    patients = PatientDataService(patients_directory)
    policy = dose_status_policy or DoseStatusPolicy()
    health_service = ApplicationHealthService(client, patients, demo_now, dose_status_policy=policy)
    app = FastAPI(title="Medication Copilot API", version="0.1.0")

    def service_for(patient_id: str) -> RuntimeMedicationService:
        try:
            patient = patients.load_patient(patient_id)
        except PatientDataError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        clock = FixedClock(demo_now) if demo_now else SystemClock(patient.source_record.patient.timezone)
        return RuntimeMedicationService(patients, patient_id, clock, policy)

    def source_review(patient_id: str) -> list[dict[str, Any]]:
        patient = service_for(patient_id).repository.load()
        included = {
            source_id
            for medication in patient.medication_plan.medications
            if medication.included_in_daily_plan
            for source_id in medication.source_medication_request_ids
        }
        flags = (patient.source_record.model_extra or {}).get("reconciliation_flags", [])
        return [
            {
                "id": medication.get("id"),
                "raw_display": medication.get("raw_display"),
                "fhir_status": medication.get("fhir_status"),
                "current_use_status": medication.get("current_use_status"),
                "validation_flags": medication.get("validation_flags", []),
                "reconciliation_flags": [
                    flag
                    for flag in flags
                    if medication.get("id") in flag.get("related_medication_ids", [])
                ],
                "included_in_plan": medication.get("id") in included,
            }
            for medication in patient.source_record.medications
        ]

    def dashboard(patient_id: str) -> dict[str, Any]:
        service = service_for(patient_id)
        patient = service.repository.load()
        readiness = patient.import_summary
        try:
            today = service.list_today_medications()
            next_dose = service.find_next_dose()
        except ValueError as exc:
            today = {"status": "review_required", "message": str(exc)}
            next_dose = {"status": "review_required", "message": str(exc)}
        doses = today if isinstance(today, list) else []
        completed = sum(item["status"] in {"taken", "taken_late"} for item in doses)
        prn = [
            {
                "name": medication.patient_friendly_name,
                "strength": medication.strength or "",
                "purpose": ", ".join(medication.purpose_labels),
                "instruction": medication.source_instruction,
            }
            for medication in patient.medication_plan.medications
            if medication.current_use_status == "confirmed_current"
            and medication.reconciliation_status == "verified"
            and medication.schedule_type == "as_needed"
        ]
        purposes: dict[str, str] = {}
        for medication in patient.medication_plan.medications:
            if medication.purpose_labels:
                purpose = ", ".join(medication.purpose_labels)
                purposes[medication.patient_friendly_name] = purpose
                full_name = f"{medication.patient_friendly_name}{' ' + medication.strength if medication.strength else ''}"
                purposes[full_name] = purpose
        return {
            "patient": {
                "id": patient.source_record.patient.id,
                "display_name": patient.source_record.patient.display_name,
                "age": patient.source_record.patient.age_at_dataset_reference_date,
                "preferred_language": patient.source_record.patient.preferred_language,
                "timezone": patient.source_record.patient.timezone,
                "allergy_status": patient.source_record.allergy_status,
            },
            "readiness": readiness.model_dump(mode="json"),
            "active_clock": service.clock.now().isoformat(),
            "today": today,
            "next_dose": next_dose,
            "progress": {
                "completed": completed,
                "total": len(doses),
                "remaining": len(doses) - completed,
                "percent": round(100 * completed / len(doses)) if doses else 0,
            },
            "prn_medications": prn,
            "purposes": purposes,
            "dose_details": _dose_presentation_labels(patient),
        }

    def action_response(patient_id: str, action: str) -> dict[str, Any]:
        service = service_for(patient_id)
        try:
            if action == "today":
                output = service.list_today_medications()
                answer = MedicationOrchestrator._format(Action.LIST_TODAY_MEDICATIONS, output)
                action_name = Action.LIST_TODAY_MEDICATIONS.value
            elif action == "next":
                output = service.find_next_dose()
                answer = output["message"]
                action_name = Action.FIND_NEXT_DOSE.value
            elif action == "history":
                output = service.show_medication_history()
                answer = MedicationOrchestrator._format(Action.SHOW_MEDICATION_HISTORY, output)
                action_name = Action.SHOW_MEDICATION_HISTORY.value
            else:
                raise HTTPException(status_code=404, detail="Unsupported action.")
            return {
                "answer": answer,
                "result": {
                    "action": action_name,
                    "tool_output": output,
                    "active_clock": service.clock.now().isoformat(),
                    "outcome": "success",
                    "response_source": "deterministic_direct_action",
                },
                "dashboard": dashboard(patient_id),
            }
        except ValueError as exc:
            outcome = "patient_not_ready" if str(exc) == UNREADY_MESSAGE else "needs_clarification"
            return {
                "answer": str(exc),
                "result": {
                    "action": action.upper(),
                    "tool_output": None,
                    "active_clock": service.clock.now().isoformat(),
                    "outcome": outcome,
                    "response_source": "deterministic_runtime_service",
                },
                "dashboard": dashboard(patient_id),
            }

    @app.get("/api/patients")
    def list_patients() -> list[dict[str, Any]]:
        return [
            summary.model_dump(mode="json", exclude={"path"}) | {"label": summary.label}
            for summary in patients.list_available_patients()
        ]

    @app.get("/api/patients/{patient_id}/dashboard")
    def get_dashboard(patient_id: str) -> dict[str, Any]:
        return dashboard(patient_id)

    @app.get("/api/patients/{patient_id}/source-record")
    def get_source_record(patient_id: str) -> list[dict[str, Any]]:
        return source_review(patient_id)

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return health_service.check()

    @app.post("/api/patients/{patient_id}/ask")
    def ask(patient_id: str, request: AskRequest) -> dict[str, Any]:
        service = service_for(patient_id)
        orchestrator = MedicationOrchestrator(service, IntentRouter(client))
        try:
            result = orchestrator.handle(UserInput(text=request.text))
            payload = result.as_dict()
            answer = _simplify_response(result.response, payload) if request.simplified else result.response
        except (OllamaError, IntentParseError) as exc:
            answer = "I could not route that request safely, so no medication action was performed. The local patient data remains available."
            payload = {
                "action": "ROUTING_ERROR",
                "tool_output": None,
                "errors": [str(exc)],
                "active_clock": service.clock.now().isoformat(),
                "outcome": "routing_error",
                "response_source": "deterministic_routing_error",
            }
        return {"answer": answer, "result": payload, "dashboard": dashboard(patient_id)}

    @app.post("/api/patients/{patient_id}/actions/{action}")
    def run_action(patient_id: str, action: str) -> dict[str, Any]:
        return action_response(patient_id, action)

    @app.post("/api/patients/{patient_id}/doses/{dose_id}/taken")
    def mark_taken(patient_id: str, dose_id: str, request: MarkTakenRequest) -> dict[str, Any]:
        service = service_for(patient_id)
        try:
            output = service.mark_dose_taken_by_id(dose_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "answer": output["message"],
            "result": {
                "action": Action.MARK_DOSE_TAKEN.value,
                "tool_output": output,
                "active_clock": service.clock.now().isoformat(),
                "outcome": "success",
                "response_source": "deterministic_exact_dose_action",
            },
            "dashboard": dashboard(patient_id),
        }

    dist = Path(frontend_dist).resolve() if frontend_dist else None
    if dist and dist.is_dir():
        assets = dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def frontend(path: str) -> FileResponse:
            candidate = (dist / path).resolve()
            if path and candidate.is_file() and dist in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")
    else:
        @app.get("/", include_in_schema=False)
        def api_root() -> dict[str, str]:
            return {"message": "Medication Copilot API", "frontend": "Run the Vite development server or build frontend/."}

    return app
