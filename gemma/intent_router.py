from __future__ import annotations

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
