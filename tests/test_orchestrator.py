from gemma.orchestrator import MedicationOrchestrator
from gemma.schemas import Action, Intent
from medication.schemas import UserInput


class StubClient:
    last_latency_ms = 2


class StubRouter:
    client = StubClient()
    def __init__(self, intent):
        self.intent = intent
    def route(self, _):
        return self.intent


def test_next_action_mapping(service):
    intent = Intent(action=Action.FIND_NEXT_DOSE, date_reference="today", confidence=1)
    result = MedicationOrchestrator(service, StubRouter(intent)).handle(
        UserInput(text="What comes next?"), "2026-08-01T10:00:00+05:30"
    )
    assert "Vitamin D3" in result.response


def test_missing_reference_clarifies(service):
    intent = Intent(action=Action.MARK_DOSE_TAKEN, confidence=1)
    result = MedicationOrchestrator(service, StubRouter(intent)).handle(UserInput(text="Mark it"))
    assert "Which saved medication" in result.response


def test_unsafe_never_executes(service):
    intent = Intent(action=Action.UNSAFE_MEDICAL_REQUEST, confidence=1)
    result = MedicationOrchestrator(service, StubRouter(intent)).handle(UserInput(text="double my dose"))
    assert "cannot recommend changes" in result.response
