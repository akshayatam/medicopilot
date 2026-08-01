from __future__ import annotations

import re

from gemma.client import OllamaClient
from gemma.prompts import REPAIR_PROMPT, SYSTEM_PROMPT
from gemma.response_parser import IntentParseError, parse_intent
from gemma.schemas import Action, Intent
from medication.safety import check_safety


class IntentRouter:
    def __init__(self, client: OllamaClient) -> None:
        self.client = client
        self.raw_model_json: str | None = None
        self.repair_model_json: str | None = None
        self.repair_used = False
        self.validation_error: str | None = None

    def route(self, text: str) -> Intent:
        self.raw_model_json = None; self.repair_model_json = None
        self.repair_used = False; self.validation_error = None
        normalized = " ".join(text.strip().split())
        safety = check_safety(normalized)
        if safety.unsafe:
            return Intent(
                action=Action.UNSAFE_MEDICAL_REQUEST,
                confidence=1,
                unsafe_reason=safety.reason,
            )
        if _is_today_schedule_request(normalized):
            self.client.last_latency_ms = None
            return Intent(
                action=Action.LIST_TODAY_MEDICATIONS,
                date_reference="today",
                confidence=1,
            )
        if _is_next_dose_request(normalized):
            self.client.last_latency_ms = None
            return Intent(
                action=Action.FIND_NEXT_DOSE,
                date_reference="today",
                confidence=1,
            )
        raw = self.client.chat(SYSTEM_PROMPT, normalized)
        self.raw_model_json = raw
        try:
            return parse_intent(raw)
        except IntentParseError as first_error:
            self.repair_used = True
            self.validation_error = str(first_error)
            repaired = self.client.chat(
                SYSTEM_PROMPT,
                f"{REPAIR_PROMPT}\nConcrete validation error:\n{first_error}\n"
                f"Invalid response for reference only (do not reproduce it):\n{raw}\n"
                f"Original user request:\n{normalized}",
            )
            self.repair_model_json = repaired
            try:
                return parse_intent(repaired)
            except IntentParseError as exc:
                self.validation_error = f"initial: {first_error}; repair: {exc}"
                raise IntentParseError(
                    f"The local model could not produce a valid intent after one repair. {exc}"
                ) from first_error


def _is_today_schedule_request(text: str) -> bool:
    """Recognize only explicit, non-clinical requests to display today's plan."""
    normalized = text.casefold().strip()
    patterns = (
        r"what does my (?:medication |medicine |dose )?schedule look like[?.!]*",
        r"what is my (?:medication |medicine |dose )?schedule(?: for today| today)?[?.!]*",
        r"(?:please )?show me my (?:medication |medicine |dose )?schedule(?: for today| today)?[?.!]*",
        r"(?:please )?show (?:me )?today'?s (?:medications|medicines|doses|schedule)[?.!]*",
    )
    return any(re.fullmatch(pattern, normalized) for pattern in patterns)


def _is_next_dose_request(text: str) -> bool:
    """Recognize explicit next-dose lookups without interpreting treatment advice."""
    normalized = text.casefold().strip()
    patterns = (
        r"what is my next (?:medication|medicine|dose|pill)[?.!]*",
        r"what (?:medication|medicine|dose|pill) (?:is|comes) next[?.!]*",
        r"what comes next[?.!]*",
        r"when is my next (?:medication|medicine|dose|pill)[?.!]*",
        r"(?:please )?(?:show|tell) me (?:my )?next (?:medication|medicine|dose|pill)[?.!]*",
    )
    return any(re.fullmatch(pattern, normalized) for pattern in patterns)
