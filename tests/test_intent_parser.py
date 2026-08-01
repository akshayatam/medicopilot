import pytest

from gemma.intent_router import IntentRouter
from gemma.response_parser import IntentParseError, parse_intent
from gemma.schemas import Action


VALID = '{"action":"FIND_NEXT_DOSE","medication_reference":null,"date_reference":"today","time_period":null,"confidence":0.9,"clarification_question":null,"unsafe_reason":null}'


def test_valid_and_invalid_parsing():
    assert parse_intent(VALID).action == Action.FIND_NEXT_DOSE
    with pytest.raises(IntentParseError):
        parse_intent("not json")
    with pytest.raises(IntentParseError):
        parse_intent('{"action":"DELETE_ALL","confidence":1}')


@pytest.mark.parametrize("payload, expected", [
    ('{"action":"FIND_NEXT_DOSE","confidence":null}', None),
    ('{"action":"FIND_NEXT_DOSE"}', None),
    ('{"action":"FIND_NEXT_DOSE","confidence":0.4}', 0.4),
])
def test_optional_confidence(payload, expected):
    assert parse_intent(payload).confidence == expected


@pytest.mark.parametrize("value", ["-0.1", "1.1", '"0.5"'])
def test_invalid_confidence_rejected(value):
    with pytest.raises(IntentParseError):
        parse_intent(f'{{"action":"FIND_NEXT_DOSE","confidence":{value}}}')


class FakeClient:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.last_latency_ms = 1
    def chat(self, *_):
        self.calls = getattr(self, "calls", []) + [_]
        return next(self.replies)


def test_router_repairs_once():
    client = FakeClient(["bad", VALID]); router = IntentRouter(client)
    assert router.route("what comes next").action == Action.FIND_NEXT_DOSE
    assert router.repair_used and router.raw_model_json == "bad" and router.repair_model_json == VALID
    assert "Concrete validation error" in client.calls[1][1]
    assert "do not reproduce" in client.calls[1][1]


def test_router_fails_after_repair():
    with pytest.raises(IntentParseError):
        IntentRouter(FakeClient(["bad", "still bad"])).route("what comes next")


def test_safety_bypasses_model():
    intent = IntentRouter(FakeClient([])).route("Should I double my dose?")
    assert intent.action == Action.UNSAFE_MEDICAL_REQUEST


def test_parser_preserves_vague_medication_reference():
    intent = parse_intent(
        '{"action":"CHECK_DOSE_STATUS","medication_reference":"heart tablet",'
        '"time_period":"morning","clarification_question":null}'
    )
    assert intent.medication_reference == "heart tablet"


def test_complete_action_discards_irrelevant_clarification_fields():
    intent = parse_intent(
        '{"action":"FIND_NEXT_DOSE","medication_reference":"tablet",'
        '"time_period":"morning","clarification_question":"Which medicine?"}'
    )
    assert intent.medication_reference is None
    assert intent.time_period is None
    assert intent.clarification_question is None


def test_needs_clarification_requires_question():
    with pytest.raises(IntentParseError, match="non-empty clarification_question"):
        parse_intent('{"action":"NEEDS_CLARIFICATION","clarification_question":"  "}')


def test_router_repairs_discarded_vague_reference():
    discarded = ('{"action":"CHECK_DOSE_STATUS","medication_reference":null,'
                 '"time_period":"morning","clarification_question":"Which heart tablet?"}')
    preserved = ('{"action":"CHECK_DOSE_STATUS","medication_reference":"heart tablet",'
                 '"time_period":"morning","clarification_question":null}')
    client = FakeClient([discarded, preserved])
    router = IntentRouter(client)
    intent = router.route("Did I take my heart tablet this morning?")
    assert intent.medication_reference == "heart tablet"
    assert router.repair_used


def test_missed_dose_action_validates_as_complete():
    intent = parse_intent('{"action":"CHECK_MISSED_DOSES","clarification_question":"ignored"}')
    assert intent.action == Action.CHECK_MISSED_DOSES
    assert intent.clarification_question is None
