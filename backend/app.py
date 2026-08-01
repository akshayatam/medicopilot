from __future__ import annotations

import tempfile
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from config import settings
from gemma.client import OllamaClient, OllamaError
from gemma.intent_router import IntentRouter
from gemma.orchestrator import MedicationOrchestrator
from gemma.response_parser import IntentParseError
from gemma.schemas import Action
from medication.clock import FixedClock, SystemClock
from medication.dose_status import DoseStatusPolicy
from medication.followup import PendingDoseFollowup, classify_contextual_reply, handle_pending_reply
from medication.health import ApplicationHealthService
from medication.patient_data_service import PatientDataError, PatientDataService
from medication.runtime_service import RuntimeMedicationService
from medication.schemas import UserInput
from voice.audio import AudioValidationError, MAX_AUDIO_BYTES, normalized_audio
from voice.providers import GemmaAudioTranscriptionProvider
from voice.schemas import PendingVoiceAction
from voice.service import VoiceInteractionService


class ChatRequest(BaseModel):
    patient_id: str
    text: str = Field(min_length=1)
    session_id: str | None = None
    simplified: bool = False
    include_debug: bool = False


class DirectActionRequest(BaseModel):
    patient_id: str
    action: Literal["today", "next", "history", "mark_next"]
    session_id: str | None = None
    simplified: bool = False
    include_debug: bool = False


class VoiceSubmitRequest(ChatRequest):
    language: Literal["English"] = "English"


class SessionRequest(BaseModel):
    patient_id: str
    session_id: str
    include_debug: bool = False


class SessionStore:
    """Process-local presentation state; no transcript or pending action is persisted."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._values: dict[str, dict[str, Any]] = {}

    def get(self, session_id: str | None, patient_id: str) -> tuple[str, dict[str, Any]]:
        with self._lock:
            key = session_id if session_id in self._values else uuid.uuid4().hex
            state = self._values.setdefault(key, {})
            if state.get("patient_id") != patient_id:
                state.clear()
                state["patient_id"] = patient_id
            return key, state

    def clear_pending(self, session_id: str, patient_id: str) -> None:
        def clear(state: dict[str, Any]) -> None:
            state.pop("pending_dose_followup", None)
            state.pop("pending_voice_action", None)
        self.apply_to_existing(session_id, patient_id, clear)

    def apply_to_existing(self, session_id: str, patient_id: str, operation):
        """Apply one confirmation atomically without accepting client dose details."""
        with self._lock:
            state = self._values.get(session_id)
            if state is None:
                raise ValueError("The pending confirmation is no longer available.")
            if state.get("patient_id") != patient_id:
                raise ValueError("The pending confirmation belongs to another patient.")
            return operation(state)


def create_app(
    *,
    patients_directory: str | Path = settings.runtime_patients_directory,
    demo_now: str | None = settings.demo_now,
    client: OllamaClient | None = None,
    dose_status_policy: DoseStatusPolicy | None = None,
) -> FastAPI:
    client = client or OllamaClient(settings.ollama_base_url, settings.ollama_model, settings.ollama_timeout_seconds)
    patients = PatientDataService(patients_directory)
    policy = dose_status_policy or DoseStatusPolicy(
        due_window_minutes=settings.dose_due_window_minutes,
        missed_after_minutes=settings.dose_missed_after_minutes,
    )
    sessions = SessionStore()
    voice_provider = GemmaAudioTranscriptionProvider(client.base_url, client.model, max(client.timeout, 90))
    app = FastAPI(title="Medication Copilot API", version="1.0.0")
    app.state.session_store = sessions
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def service_for(patient_id: str) -> RuntimeMedicationService:
        try:
            patient = patients.load_patient(patient_id)
        except PatientDataError as exc:
            raise HTTPException(404, str(exc)) from exc
        clock = FixedClock(demo_now) if demo_now else SystemClock(patient.source_record.patient.timezone)
        return RuntimeMedicationService(patients, patient_id, clock, policy)

    app.state.service_for = service_for

    def status_payload(patient_id: str) -> dict[str, Any]:
        try:
            patient = patients.reload_patient(patient_id)
        except PatientDataError as exc:
            raise HTTPException(404, str(exc)) from exc
        ready = patient.import_summary
        return {
            "patient_id": patient_id,
            "display_name": patient.source_record.patient.display_name,
            "age": patient.source_record.patient.age_at_dataset_reference_date,
            "preferred_language": patient.source_record.patient.preferred_language,
            "timezone": patient.source_record.patient.timezone,
            "readiness": "Ready" if ready.ready_for_medication_tracking else "Needs review",
            "ready": ready.ready_for_medication_tracking,
            "confirmed_medication_count": sum(m.included_in_daily_plan for m in patient.medication_plan.medications),
            "allergy_status": patient.source_record.allergy_status,
            "blocking_issues": ready.blocking_issues,
            "warnings": ready.warnings,
        }

    def safe_call(call, fallback: dict[str, Any]) -> Any:
        try:
            return call()
        except ValueError as exc:
            return fallback | {"message": str(exc)}

    def dashboard_payload(patient_id: str) -> dict[str, Any]:
        service = service_for(patient_id)
        patient = patients.reload_patient(patient_id)
        medications = [
            {
                "medication_id": med.id,
                "name": med.patient_friendly_name,
                "strength": med.strength or "",
                "purpose": ", ".join(med.purpose_labels),
                "appearance": service._verified_appearance(med),
                "schedule_type": med.schedule_type,
            }
            for med in patient.medication_plan.medications
            if med.current_use_status == "confirmed_current" and med.reconciliation_status == "verified"
        ]
        today = safe_call(service.list_today_medications, {"status": "review_required"})
        next_dose = safe_call(service.find_next_dose, {"status": "review_required"})
        doses = today if isinstance(today, list) else []
        completed = sum(item["status"] in {"taken", "taken_late"} for item in doses)
        missed = sum(item["status"] == "missed" for item in doses)
        remaining = sum(item["status"] in {"upcoming", "due"} for item in doses)
        return {
            "patient": status_payload(patient_id),
            "active_clock": service.clock.now().isoformat(),
            "today": today,
            "next_dose": next_dose,
            "progress": {"completed": completed, "total": len(doses), "missed": missed, "remaining": remaining},
            "medications": medications,
            "as_needed": [item for item in medications if item["schedule_type"] == "as_needed"],
            "dose_status_policy": service.policy_payload(),
        }

    def review_payload(patient_id: str) -> list[dict[str, Any]]:
        patient = patients.reload_patient(patient_id)
        included = {sid for med in patient.medication_plan.medications if med.included_in_daily_plan for sid in med.source_medication_request_ids}
        flags = (patient.source_record.model_extra or {}).get("reconciliation_flags", [])
        return [{
            "id": med.get("id"), "raw_display": med.get("raw_display"), "fhir_status": med.get("fhir_status"),
            "current_use_status": med.get("current_use_status"), "validation_flags": med.get("validation_flags", []),
            "reconciliation_flags": [flag for flag in flags if med.get("id") in flag.get("related_medication_ids", [])],
            "included_in_plan": med.get("id") in included,
        } for med in patient.source_record.medications]

    def simplify(answer: str, payload: dict[str, Any]) -> str:
        if payload.get("outcome") in {"unsafe_request", "patient_not_ready", "routing_error"}:
            return answer
        output = payload.get("tool_output")
        if isinstance(output, dict) and output.get("message"):
            return str(output["message"])
        return answer

    def response(payload: dict[str, Any], session_id: str, answer: str, include_debug: bool, pending: dict | None = None) -> dict[str, Any]:
        value = {"session_id": session_id, "answer": answer, "action": payload.get("action"), "outcome": payload.get("outcome", "success"), "pending_confirmation": pending}
        if include_debug:
            value["debug"] = payload
        return value

    @app.get("/api/patients")
    def list_patients() -> list[dict[str, Any]]:
        return [summary.model_dump(mode="json", exclude={"path"}) | {"label": summary.label} for summary in patients.list_available_patients()]

    @app.get("/api/patients/{patient_id}/dashboard")
    def get_dashboard(patient_id: str) -> dict[str, Any]:
        return dashboard_payload(patient_id)

    @app.get("/api/patients/{patient_id}/history")
    def get_history(patient_id: str, limit: int = 10) -> dict[str, Any]:
        return {"items": safe_call(lambda: service_for(patient_id).show_medication_history(limit=limit), {"status": "review_required"})}

    @app.get("/api/patients/{patient_id}/source-review")
    def get_source_review(patient_id: str) -> dict[str, Any]:
        return {"notice": "Read-only source orders; never used as the daily medication plan.", "items": review_payload(patient_id)}

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return ApplicationHealthService(client, patients, demo_now, dose_status_policy=policy).check()

    @app.post("/api/chat")
    def chat(request: ChatRequest) -> dict[str, Any]:
        service = service_for(request.patient_id)
        session_id, state = sessions.get(request.session_id, request.patient_id)
        text = " ".join(request.text.strip().split())
        kind = classify_contextual_reply(text)
        raw_pending = state.get("pending_dose_followup")
        if kind is not None:
            try:
                output = handle_pending_reply(service, PendingDoseFollowup.model_validate(raw_pending) if raw_pending else None, text)
                payload = {"action": "CONFIRM_MISSED_DOSE", "tool_output": output, "active_clock": service.clock.now().isoformat(), "outcome": "success", "response_source": "deterministic_pending_confirmation"}
                return response(payload, session_id, output["message"], request.include_debug)
            except ValueError as exc:
                payload = {"action": "CONFIRM_MISSED_DOSE", "tool_output": None, "active_clock": service.clock.now().isoformat(), "outcome": "needs_clarification", "errors": [str(exc)]}
                return response(payload, session_id, str(exc), request.include_debug)
            finally:
                state.pop("pending_dose_followup", None)
        state.pop("pending_dose_followup", None)
        try:
            result = MedicationOrchestrator(service, IntentRouter(client)).handle(UserInput(text=text))
            payload = result.as_dict() | {"selected_patient_id": request.patient_id, "readiness": patients.get_readiness(request.patient_id).model_dump(mode="json")}
            answer = result.response
        except (OllamaError, IntentParseError) as exc:
            answer = "I could not route that request safely, so no medication action was performed. The local patient data remains available."
            payload = {"action": "ROUTING_ERROR", "tool_output": None, "errors": [str(exc)], "active_clock": service.clock.now().isoformat(), "outcome": "routing_error", "response_source": "deterministic_routing_error"}
            result = None
        pending_payload = None
        if result and result.action == "CHECK_MISSED_DOSES" and isinstance(result.tool_output, dict) and len(result.tool_output.get("doses", [])) == 1:
            pending = PendingDoseFollowup.from_missed_dose(request.patient_id, service.patient_data_version(), result.tool_output["doses"][0], service.clock.now())
            state["pending_dose_followup"] = pending.model_dump(mode="json")
            state.pop("last_missed_confirmation", None)
            pending_payload = {"type": pending.type, "prompt": pending.prompt, "expires_at": pending.expires_at.isoformat()}
        return response(payload, session_id, simplify(answer, payload) if request.simplified else answer, request.include_debug, pending_payload)

    @app.post("/api/actions")
    def direct_action(request: DirectActionRequest) -> dict[str, Any]:
        service = service_for(request.patient_id)
        session_id, state = sessions.get(request.session_id, request.patient_id)
        state.pop("pending_dose_followup", None)
        try:
            if request.action == "today":
                output = service.list_today_medications(); action = Action.LIST_TODAY_MEDICATIONS
            elif request.action == "next":
                output = service.find_next_dose(); action = Action.FIND_NEXT_DOSE
            elif request.action == "history":
                output = service.show_medication_history(); action = Action.SHOW_MEDICATION_HISTORY
            else:
                upcoming = service.find_next_dose(); action = Action.MARK_DOSE_TAKEN
                output = upcoming if upcoming.get("status") not in {"upcoming", "due"} else service.mark_dose_taken(upcoming["medication"])
            answer = MedicationOrchestrator._format(action, output)
            payload = {"selected_patient_id": request.patient_id, "action": action.value, "tool_output": output, "active_clock": service.clock.now().isoformat(), "outcome": "success", "response_source": "deterministic_direct_action"}
        except ValueError as exc:
            answer = str(exc); payload = {"action": request.action.upper(), "tool_output": None, "active_clock": service.clock.now().isoformat(), "outcome": "patient_not_ready", "response_source": "deterministic_runtime_service"}
        return response(payload, session_id, simplify(answer, payload) if request.simplified else answer, request.include_debug)

    @app.post("/api/voice/transcribe")
    async def transcribe_voice(patient_id: str = Form(...), language: str = Form("English"), audio: UploadFile = File(...)) -> dict[str, Any]:
        service_for(patient_id)
        if language != "English":
            raise HTTPException(422, "Only English voice input is currently tested.")
        content = await audio.read(MAX_AUDIO_BYTES + 1)
        if len(content) > MAX_AUDIO_BYTES:
            raise HTTPException(413, "The audio recording is too large.")
        suffix = Path(audio.filename or "audio.wav").suffix or ".wav"
        try:
            with tempfile.TemporaryDirectory(prefix="medicopilot-upload-") as directory:
                source = Path(directory) / f"upload{suffix}"
                source.write_bytes(content)
                with normalized_audio(source) as (normalized, _metadata):
                    result = voice_provider.transcribe(normalized, language)
        except AudioValidationError as exc:
            raise HTTPException(422, str(exc)) from exc
        return result.model_dump(mode="json")

    @app.post("/api/voice/submit")
    def submit_voice(request: VoiceSubmitRequest) -> dict[str, Any]:
        session_id, state = sessions.get(request.session_id, request.patient_id)
        interaction = VoiceInteractionService(service_for(request.patient_id), IntentRouter(client))
        try:
            result, pending = interaction.submit_transcript(request.text)
        except (OllamaError, IntentParseError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
        if pending:
            state["pending_voice_action"] = pending.model_dump(mode="json")
            prompt = f"Record {pending.medication_display}, scheduled at {pending.scheduled_at.strftime('%-I:%M %p')} on {pending.scheduled_at.date().isoformat()}, as taken?"
            if pending.appearance:
                prompt += f" Appearance saved in your verified plan: {pending.appearance}"
            return {"session_id": session_id, "answer": "Transcript approved.", "action": pending.action, "outcome": "needs_confirmation", "pending_confirmation": {"type": "voice_mark_taken", "prompt": prompt}}
        payload = result.as_dict() | {"selected_patient_id": request.patient_id, "voice_input": True}
        pending_payload = None
        if result.action == "CHECK_MISSED_DOSES" and isinstance(result.tool_output, dict) and len(result.tool_output.get("doses", [])) == 1:
            service = service_for(request.patient_id)
            followup = PendingDoseFollowup.from_missed_dose(
                request.patient_id, service.patient_data_version(), result.tool_output["doses"][0], service.clock.now()
            )
            state["pending_dose_followup"] = followup.model_dump(mode="json")
            state.pop("last_missed_confirmation", None)
            pending_payload = {"type": followup.type, "prompt": followup.prompt, "expires_at": followup.expires_at.isoformat()}
        return response(payload, session_id, result.response, request.include_debug, pending_payload)

    @app.post("/api/voice/confirm")
    def confirm_voice(request: SessionRequest) -> dict[str, Any]:
        session_id, state = sessions.get(request.session_id, request.patient_id)
        raw = state.pop("pending_voice_action", None)
        if not raw:
            raise HTTPException(409, "No pending voice action remains.")
        try:
            pending = PendingVoiceAction.model_validate(raw)
            output = VoiceInteractionService(service_for(request.patient_id), IntentRouter(client)).confirm(pending)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        payload = {"action": pending.action, "tool_output": output, "outcome": "success", "response_source": "deterministic_runtime_service", "voice_input": True}
        return response(payload, session_id, output["message"], request.include_debug)

    @app.post("/api/confirmations/missed-dose")
    def confirm_missed_dose(request: SessionRequest) -> dict[str, Any]:
        service = service_for(request.patient_id)

        def confirm(state: dict[str, Any]) -> dict[str, Any]:
            raw = state.get("pending_dose_followup")
            if raw is None:
                receipt = state.get("last_missed_confirmation")
                if receipt is not None:
                    return receipt
                raise ValueError("No pending missed-dose confirmation remains.")
            try:
                pending = PendingDoseFollowup.model_validate(raw)
                output = handle_pending_reply(service, pending, "yes")
            except ValueError as exc:
                if "expired" in str(exc).casefold():
                    state.pop("pending_dose_followup", None)
                raise
            payload = {
                "action": "CONFIRM_MISSED_DOSE",
                "tool_output": output,
                "active_clock": service.clock.now().isoformat(),
                "outcome": "success",
                "response_source": "deterministic_pending_confirmation",
            }
            result = response(payload, request.session_id, output["message"], request.include_debug)
            state.pop("pending_dose_followup", None)
            state["last_missed_confirmation"] = result
            return result

        try:
            return sessions.apply_to_existing(request.session_id, request.patient_id, confirm)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/session/cancel")
    def cancel(request: SessionRequest) -> dict[str, Any]:
        try:
            sessions.clear_pending(request.session_id, request.patient_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"session_id": request.session_id, "status": "cancelled", "message": "Okay. I did not change the dose record."}

    return app


app = create_app()
