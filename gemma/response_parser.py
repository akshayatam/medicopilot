from __future__ import annotations

import json

from pydantic import ValidationError

from gemma.schemas import Intent


class IntentParseError(ValueError):
    pass


def parse_intent(raw: str) -> Intent:
    if not raw or not raw.strip():
        raise IntentParseError("The model returned an empty response")
    try:
        value = json.loads(raw.strip())
        if not isinstance(value, dict):
            raise IntentParseError("The model response is not a JSON object")
        return Intent.model_validate(value)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise IntentParseError(f"Invalid structured model response: {exc}") from exc
