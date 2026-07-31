from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from medication.models import DoseLog, Medication
from medication.repository import MedicationRepository


class MedicationService:
    def __init__(self, repository: MedicationRepository) -> None:
        self.repository = repository

    def list_today_medications(
        self, date: str, time_bounds: tuple[int, int] | None = None
    ) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []

        for log in self.repository.dose_logs:
            if not log.scheduled_at.startswith(date):
                continue
            if time_bounds:
                hour = datetime.fromisoformat(log.scheduled_at).hour
                if not time_bounds[0] <= hour < time_bounds[1]:
                    continue

            medication = self.repository.get_medication_by_id(log.medication_id)
            if medication is None:
                continue

            results.append(
                {
                    "name": medication.name,
                    "strength": medication.strength,
                    "purpose": medication.purpose_label,
                    "scheduled_at": log.scheduled_at,
                    "status": log.status,
                    "taken_at": log.taken_at or "",
                }
            )

        return sorted(results, key=lambda item: item["scheduled_at"])

    def check_dose_status(
        self,
        medication_reference: str,
        date: str,
        time_bounds: tuple[int, int] | None = None,
    ) -> dict[str, str]:
        medication = self._require_medication(medication_reference)

        matching_logs = [
            log
            for log in self.repository.dose_logs
            if log.medication_id == medication.id
            and log.scheduled_at.startswith(date)
            and (
                time_bounds is None
                or time_bounds[0] <= datetime.fromisoformat(log.scheduled_at).hour < time_bounds[1]
            )
        ]

        if not matching_logs:
            return {
                "medication": f"{medication.name} {medication.strength}",
                "status": "not scheduled",
                "message": f"No dose is scheduled for {date}.",
            }

        log = sorted(matching_logs, key=lambda item: item.scheduled_at)[0]
        if log.status in {"taken", "taken_late"}:
            return {
                "medication": f"{medication.name} {medication.strength}",
                "status": "taken",
                "message": (
                    f"{medication.name} {medication.strength} was recorded "
                    f"as taken at {self._display_time(log.taken_at)}."
                ),
            }

        return {
            "medication": f"{medication.name} {medication.strength}",
            "status": log.status,
            "message": (
                f"{medication.name} {medication.strength} is currently "
                f"marked as {log.status}."
            ),
        }

    def find_next_dose(
        self,
        now_iso: str,
    ) -> dict[str, str]:
        now = datetime.fromisoformat(now_iso)

        upcoming: list[tuple[datetime, DoseLog, Medication]] = []
        for log in self.repository.dose_logs:
            if log.status in {"taken", "taken_late"}:
                continue

            scheduled = datetime.fromisoformat(log.scheduled_at)
            if scheduled < now:
                continue

            medication = self.repository.get_medication_by_id(log.medication_id)
            if medication is not None:
                upcoming.append((scheduled, log, medication))

        if not upcoming:
            return {
                "status": "none",
                "message": "There are no upcoming doses in the local schedule.",
            }

        scheduled, _, medication = min(upcoming, key=lambda item: item[0])
        return {
            "status": "upcoming",
            "medication": f"{medication.name} {medication.strength}",
            "scheduled_at": scheduled.isoformat(),
            "message": (
                f"The next dose is {medication.name} {medication.strength} "
                f"at {scheduled.strftime('%I:%M %p')}."
            ),
        }

    def mark_dose_taken(
        self,
        medication_reference: str,
        date: str,
        taken_at: str | None = None,
    ) -> dict[str, str]:
        medication = self._require_medication(medication_reference)

        matching_logs = [
            log
            for log in self.repository.dose_logs
            if log.medication_id == medication.id
            and log.scheduled_at.startswith(date)
        ]

        if not matching_logs:
            raise ValueError(
                f"No scheduled dose found for {medication.name} on {date}."
            )

        log = sorted(matching_logs, key=lambda item: item.scheduled_at)[0]

        if log.status in {"taken", "taken_late"}:
            return {
                "status": "already_taken",
                "message": (
                    f"{medication.name} was already marked as taken at "
                    f"{self._display_time(log.taken_at)}."
                ),
            }

        if taken_at is None:
            timezone = ZoneInfo(self.repository.patient.timezone)
            taken_at = datetime.now(timezone).isoformat(timespec="seconds")

        log.status = "taken"
        log.taken_at = taken_at
        log.recorded_by = "patient"
        log.source = "app_event"
        self.repository.save()

        return {
            "status": "taken",
            "message": (
                f"{medication.name} {medication.strength} was marked as taken "
                f"at {self._display_time(taken_at)}."
            ),
        }

    def get_saved_instructions(self, medication_reference: str) -> dict[str, str]:
        medication = self._require_medication(medication_reference)
        return {
            "medication": f"{medication.name} {medication.strength}",
            "instructions": medication.instructions,
            "source": medication.source,
        }

    def show_medication_history(
        self, medication_reference: str | None = None, limit: int = 10
    ) -> list[dict[str, str]]:
        medication = (
            self._require_medication(medication_reference)
            if medication_reference
            else None
        )
        logs = [
            log
            for log in self.repository.dose_logs
            if medication is None or log.medication_id == medication.id
        ]
        results = []
        for log in sorted(logs, key=lambda item: item.scheduled_at, reverse=True)[:limit]:
            med = self.repository.get_medication_by_id(log.medication_id)
            if med:
                results.append(
                    {
                        "medication": f"{med.name} {med.strength}",
                        "scheduled_at": log.scheduled_at,
                        "status": log.status,
                        "taken_at": log.taken_at or "",
                    }
                )
        return results

    def _require_medication(self, reference: str) -> Medication:
        matches = self.repository.find_medications(reference)
        if not matches:
            raise ValueError(f"Medication not found: {reference}")
        if len(matches) > 1:
            names = ", ".join(f"{m.name} {m.strength}" for m in matches)
            raise ValueError(f"Medication reference is ambiguous. Matches: {names}")
        return matches[0]

    @staticmethod
    def _display_time(timestamp: str | None) -> str:
        if not timestamp:
            return "an unknown time"
        return datetime.fromisoformat(timestamp).strftime("%I:%M %p")
