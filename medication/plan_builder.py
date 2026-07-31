from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from medication.schemas import MedicationPlanItem


def build_plan(document: dict[str, Any]) -> dict[str, Any]:
    medications = [MedicationPlanItem.model_validate(m) for m in document.get("medication_plan", {}).get("medications", [])]
    included = [m for m in medications if m.included_in_daily_plan]
    document["medication_plan"]["medications"] = [m.model_dump(mode="json") for m in medications]
    document["medication_plan"]["daily_medication_ids"] = [m.id for m in included]
    document["medication_plan"]["source"] = document["medication_plan"].get("source", "explicit_reconciliation_record")
    return document


def generate_scheduled_doses(document: dict[str, Any], start_date: date, days: int) -> list[dict[str, Any]]:
    if days < 1:
        raise ValueError("days must be positive")
    timezone = document.get("source_record", {}).get("patient", {}).get("timezone")
    if not timezone:
        raise ValueError("timezone is required for scheduled dose generation")
    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("timezone must be a valid IANA timezone") from exc
    output: list[dict[str, Any]] = []
    for raw in document.get("medication_plan", {}).get("medications", []):
        med = MedicationPlanItem.model_validate(raw)
        if not med.included_in_daily_plan or med.current_use_status != "confirmed_current":
            continue
        if med.schedule_type == "as_needed":
            continue
        for day_offset in range(days):
            current = start_date + timedelta(days=day_offset)
            for schedule in med.reminder_schedule:
                hour, minute = (int(part) for part in schedule.time.split(":"))
                scheduled = datetime(current.year, current.month, current.day, hour, minute, tzinfo=zone)
                output.append({
                    "id": f"dose_{med.id}_{scheduled.strftime('%Y%m%dT%H%M%z')}",
                    "medication_id": med.id,
                    "scheduled_at": scheduled.isoformat(),
                    "status": "upcoming",
                    "taken_at": None,
                    "recorded_by": None,
                    "source": "app_event",
                })
    return sorted(output, key=lambda item: (item["scheduled_at"], item["medication_id"]))

