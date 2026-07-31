from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Literal

from gemma.intent_router import IntentRouter
from gemma.response_parser import IntentParseError
from gemma.schemas import Action, Intent
from medication.safety import EMERGENCY_REFUSAL, STANDARD_REFUSAL, check_safety
from medication.schemas import UserInput
from medication.service import MedicationService
from medication.time_resolver import DateTimeResolver
from medication.runtime_service import UNREADY_MESSAGE


@dataclass
class CopilotResult:
    response: str
    intent: dict[str, Any]
    action: str
    tool_output: Any = None
    model_latency_ms: float | None = None
    medication_resolver_result: dict[str, Any] | None = None
    response_source: str = "deterministic_template"
    errors: list[str] | None = None
    raw_model_json: str | None = None
    repair_model_json: str | None = None
    repair_used: bool = False
    active_clock: str | None = None
    tool_executed: str | None = None
    outcome: Literal[
        "success", "needs_clarification", "patient_not_ready",
        "medication_not_found", "unsafe_request", "out_of_scope",
        "routing_error", "persistence_error",
    ] = "success"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class MedicationOrchestrator:
    def __init__(self, service: MedicationService, router: IntentRouter) -> None:
        self.service = service
        self.router = router

    def handle(self, user_input: UserInput, now: str | None = None) -> CopilotResult:
        text = user_input.text or ""
        safety = check_safety(text)
        if safety.unsafe:
            intent = Intent(
                action=Action.UNSAFE_MEDICAL_REQUEST, confidence=1,
                unsafe_reason=safety.reason,
            )
            result = self._result(safety.response or STANDARD_REFUSAL, intent, None, None)
            result.outcome = "unsafe_request"
            result.active_clock = self._active_clock()
            return result
        try:
            intent = self.router.route(text)
        except IntentParseError as exc:
            return CopilotResult(
                response="I could not reliably understand that request, so no medication action was performed. Please try rephrasing it.",
                intent={}, action="ROUTING_ERROR", model_latency_ms=self.router.client.last_latency_ms,
                errors=[str(exc)], raw_model_json=getattr(self.router, "raw_model_json", None),
                repair_model_json=getattr(self.router, "repair_model_json", None),
                repair_used=bool(getattr(self.router, "repair_used", False)),
                active_clock=self._active_clock(), response_source="deterministic_routing_error",
                outcome="routing_error",
            )
        latency = self.router.client.last_latency_ms

        if intent.action == Action.UNSAFE_MEDICAL_REQUEST:
            response = EMERGENCY_REFUSAL if safety.emergency else STANDARD_REFUSAL
            result = self._result(response, intent, None, latency)
            result.outcome = "unsafe_request"; result.active_clock = self._active_clock()
            self._attach_routing_debug(result); return result
        if intent.action == Action.NEEDS_CLARIFICATION:
            result = self._result(
                intent.clarification_question
                or "Which saved medication do you mean? Please provide its name or purpose.",
                intent, None, latency,
            )
            result.outcome = "needs_clarification"
            result.active_clock = self._active_clock(); self._attach_routing_debug(result); return result
        if intent.action == Action.OUT_OF_SCOPE:
            result = self._result(
                "I can only help navigate the medication schedule, saved instructions, and dose history in this local synthetic record.",
                intent, None, latency,
            )
            result.outcome = "out_of_scope"
            result.active_clock = self._active_clock(); self._attach_routing_debug(result); return result

        if hasattr(self.service, "clock"):
            clock_now = self.service.clock.now()
            timezone = self.service.repository.load().source_record.patient.timezone
            resolver = DateTimeResolver.from_iso(timezone, clock_now.isoformat())
        else:
            resolver = DateTimeResolver.from_iso(self.service.repository.patient.timezone, now)
        date_value = resolver.resolve_date(intent.date_reference).isoformat()
        try:
            resolution = None
            if intent.medication_reference and hasattr(self.service, "resolve"):
                resolution = self.service.resolve(intent.medication_reference).model_dump(mode="json")
            output = self._execute(
                intent, date_value, resolver.now, resolver.period_bounds(intent.time_period)
            )
            result = self._result(self._format(intent.action, output), intent, output, latency)
            result.medication_resolver_result = resolution
            result.tool_executed = intent.action.value
            result.active_clock = self._active_clock()
            self._attach_routing_debug(result)
            return result
        except ValueError as exc:
            result = self._result(str(exc), intent, None, latency)
            if intent.medication_reference and hasattr(self.service, "resolve"):
                result.medication_resolver_result = self.service.resolve(intent.medication_reference).model_dump(mode="json")
            result.outcome = self._expected_outcome(str(exc), result.medication_resolver_result)
            result.active_clock = self._active_clock()
            self._attach_routing_debug(result)
            return result

    @staticmethod
    def _expected_outcome(message: str, resolution: dict[str, Any] | None) -> str:
        if message == UNREADY_MESSAGE:
            return "patient_not_ready"
        status = resolution.get("status") if resolution else None
        if status == "AMBIGUOUS" or message.startswith("Which saved medication"):
            return "needs_clarification"
        if status == "NOT_FOUND":
            return "medication_not_found"
        return "needs_clarification"

    def _active_clock(self) -> str | None:
        if hasattr(self.service, "clock"):
            return self.service.clock.now().isoformat()
        return None

    def _attach_routing_debug(self, result: CopilotResult) -> None:
        result.raw_model_json = getattr(self.router, "raw_model_json", None)
        result.repair_model_json = getattr(self.router, "repair_model_json", None)
        result.repair_used = bool(getattr(self.router, "repair_used", False))

    def _execute(
        self,
        intent: Intent,
        date_value: str,
        now: datetime,
        time_bounds: tuple[int, int] | None,
    ) -> Any:
        reference_actions = {
            Action.CHECK_DOSE_STATUS,
            Action.MARK_DOSE_TAKEN,
            Action.GET_SAVED_INSTRUCTIONS,
        }
        if intent.action in reference_actions and not intent.medication_reference:
            raise ValueError("Which saved medication do you mean? Please provide its name or purpose.")
        if intent.action == Action.LIST_TODAY_MEDICATIONS:
            return self.service.list_today_medications(date_value, time_bounds)
        if intent.action == Action.CHECK_DOSE_STATUS:
            return self.service.check_dose_status(
                intent.medication_reference or "", date_value, time_bounds
            )
        if intent.action == Action.FIND_NEXT_DOSE:
            return self.service.find_next_dose(now.isoformat())
        if intent.action == Action.MARK_DOSE_TAKEN:
            return self.service.mark_dose_taken(
                intent.medication_reference or "", date_value, now.isoformat(timespec="seconds")
            )
        if intent.action == Action.GET_SAVED_INSTRUCTIONS:
            return self.service.get_saved_instructions(intent.medication_reference or "")
        if intent.action == Action.SHOW_MEDICATION_HISTORY:
            return self.service.show_medication_history(intent.medication_reference)
        raise ValueError("That action is not supported.")

    @staticmethod
    def _format(action: Action, output: Any) -> str:
        if isinstance(output, dict) and "message" in output:
            return str(output["message"])
        if action == Action.GET_SAVED_INSTRUCTIONS:
            return f"Saved instructions for {output['medication']}: {output['instructions']} Source: {output['source']}."
        if action == Action.LIST_TODAY_MEDICATIONS:
            if not output:
                return "No doses are stored for that date."
            return "\n".join(
                f"• {x['name']} {x['strength']} — {datetime.fromisoformat(x['scheduled_at']).strftime('%I:%M %p')} — {x['status']}"
                for x in output
            )
        if action == Action.SHOW_MEDICATION_HISTORY:
            if not output:
                return "No dose history was found in the local record."
            return "\n".join(
                f"• {x['medication']} — {x['scheduled_at']} — {x['status']}"
                for x in output
            )
        return str(output)

    @staticmethod
    def _result(response: str, intent: Intent, output: Any, latency: float | None) -> CopilotResult:
        return CopilotResult(
            response=response,
            intent=intent.model_dump(mode="json"),
            action=intent.action.value,
            tool_output=output,
            model_latency_ms=latency,
        )
