import pytest

from medication.safety import check_safety
from medication.time_resolver import DateTimeResolver


@pytest.mark.parametrize("text", [
    "Should I double my dose?", "Can these pills interact?", "Can I stop taking it?",
    "What medicine should I take for pain?", "I overdosed",
])
def test_unsafe_requests(text):
    assert check_safety(text).unsafe


def test_safe_schedule_request():
    assert not check_safety("What comes next?").unsafe


@pytest.mark.parametrize("text", [
    "I missed yesterday's dose. What should I do?",
    "How much insulin should I take?",
    "I missed yesterday's shot, I take two today.",
])
def test_missed_dose_and_insulin_advice_are_refused(text):
    assert check_safety(text).unsafe


def test_time_resolution():
    resolver = DateTimeResolver.from_iso("Asia/Kolkata", "2026-08-01T10:00:00+05:30")
    assert resolver.resolve_date("today").isoformat() == "2026-08-01"
    assert resolver.period_bounds("this evening") == (17, 22)
