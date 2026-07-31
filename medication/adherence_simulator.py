from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Any

from medication.schemas import DoseLogRecord


def simulate_adherence(
    scheduled_doses: list[dict[str, Any]], seed: int, taken_probability: float = 0.85,
    late_probability: float = 0.10,
) -> list[dict[str, Any]]:
    if not 0 <= taken_probability <= 1 or not 0 <= late_probability <= 1:
        raise ValueError("probabilities must be between zero and one")
    if taken_probability + late_probability > 1:
        raise ValueError("taken and late probabilities cannot total more than one")
    rng = random.Random(seed)
    parameters = {
        "seed": seed,
        "taken_probability": taken_probability,
        "late_probability": late_probability,
        "statement": "Synthetic scenario parameters; not real-world adherence statistics.",
    }
    result: list[dict[str, Any]] = []
    for item in scheduled_doses:
        roll = rng.random()
        scheduled = datetime.fromisoformat(str(item["scheduled_at"]))
        if roll < taken_probability:
            status, taken_at = "taken", scheduled + timedelta(minutes=rng.randint(-5, 15))
        elif roll < taken_probability + late_probability:
            status, taken_at = "taken_late", scheduled + timedelta(minutes=rng.randint(31, 180))
        else:
            status, taken_at = "missed", None
        record = {
            **item,
            "status": status,
            "taken_at": taken_at.isoformat() if taken_at else None,
            "recorded_by": "synthetic_simulator",
            "source": "synthetic_adherence_simulation",
            "generation_parameters": parameters,
        }
        result.append(DoseLogRecord.model_validate(record).model_dump(mode="json"))
    return result

