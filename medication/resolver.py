from __future__ import annotations

from enum import Enum
from typing import Iterable

from pydantic import BaseModel, Field

from medication.schemas import MedicationPlanItem


class ResolutionStatus(str, Enum):
    MATCHED = "MATCHED"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_FOUND = "NOT_FOUND"


class ResolutionMatch(BaseModel):
    medication_id: str
    display_name: str


class MedicationResolution(BaseModel):
    status: ResolutionStatus
    query: str
    matches: list[ResolutionMatch] = Field(default_factory=list)


class MedicationResolver:
    def resolve(self, query: str, medications: Iterable[MedicationPlanItem]) -> MedicationResolution:
        normalized = " ".join(query.casefold().split())
        candidates: list[tuple[int, MedicationPlanItem]] = []
        for med in medications:
            if not (med.current_use_status == "confirmed_current" and med.reconciliation_status == "verified"):
                continue
            exact = {med.patient_friendly_name.casefold(), *(a.casefold() for a in med.aliases), *(p.casefold() for p in med.purpose_labels)}
            if med.strength:
                exact.add(f"{med.patient_friendly_name} {med.strength}".casefold())
            schedule_labels = {f"{s.period} tablet".casefold() for s in med.reminder_schedule if s.period}
            exact |= schedule_labels
            if normalized in exact:
                candidates.append((2, med)); continue
            if normalized and any(normalized in term or term in normalized for term in exact if term):
                candidates.append((1, med))
        if not candidates:
            return MedicationResolution(status=ResolutionStatus.NOT_FOUND, query=query)
        best = max(score for score, _ in candidates)
        matches = list({m.id: m for score, m in candidates if score == best}.values())
        payload = [ResolutionMatch(medication_id=m.id, display_name=f"{m.patient_friendly_name}{' ' + m.strength if m.strength else ''}") for m in matches]
        return MedicationResolution(status=ResolutionStatus.MATCHED if len(payload) == 1 else ResolutionStatus.AMBIGUOUS, query=query, matches=payload)
