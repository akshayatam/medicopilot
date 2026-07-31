from __future__ import annotations

import re
from typing import Any


_SIMPLE_SINGLE_INGREDIENT = re.compile(
    r"^(?P<name>.+?)\s+(?P<strength>\d+(?:\.\d+)?\s*(?:mg|mcg|g|mL|IU|units?))"
    r"(?:\s+(?P<form>.+))?$",
    re.IGNORECASE,
)


def normalize_medication(concept: dict[str, Any] | None) -> dict[str, Any]:
    """Conservatively normalize a Medication CodeableConcept.

    Structured coding is retained verbatim. Combination/concentration strings are
    deliberately not decomposed without a local RxNorm dictionary.
    """
    concept = concept if isinstance(concept, dict) else {}
    coding = next((c for c in concept.get("coding", []) if isinstance(c, dict)), {})
    raw = coding.get("display") or concept.get("text")
    result = {
        "rxnorm_code": str(coding["code"]) if coding.get("code") is not None else None,
        "code_system": coding.get("system"),
        "raw_display": raw,
        "patient_friendly_name": raw,
        "ingredients": [],
        "strength": None,
        "dose_form": None,
        "brand_name": None,
        "validation_flags": [],
        "normalization_source": "raw_display_fallback",
    }
    if not raw:
        result["patient_friendly_name"] = None
        result["validation_flags"].append("medication_display_not_fully_normalized")
        return result

    # Slash and plus commonly denote concentrations or combinations. Preserving
    # these is safer than pretending a regex produced structured ingredients.
    if "/" in raw or " + " in raw or " and " in raw.casefold():
        result["validation_flags"].append("medication_display_not_fully_normalized")
        return result

    match = _SIMPLE_SINGLE_INGREDIENT.match(raw.strip())
    if not match:
        result["validation_flags"].append("medication_display_not_fully_normalized")
        return result

    name = match.group("name").strip()
    strength = match.group("strength").strip()
    form = match.group("form").strip() if match.group("form") else None
    result.update(
        patient_friendly_name=name,
        ingredients=[{"name": name.casefold(), "strength": strength.casefold()}],
        strength=strength,
        dose_form=form.casefold() if form else None,
        normalization_source="conservative_display_parser",
    )
    return result

