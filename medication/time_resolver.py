from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo


PERIODS = {
    "morning": (0, 12), "this morning": (0, 12),
    "afternoon": (12, 17), "this afternoon": (12, 17),
    "evening": (17, 22), "this evening": (17, 22),
    "tonight": (17, 24),
}


class DateTimeResolver:
    def __init__(self, timezone: str, now: datetime | None = None) -> None:
        self.timezone = ZoneInfo(timezone)
        self.now = (now or datetime.now(self.timezone)).astimezone(self.timezone)

    @classmethod
    def from_iso(cls, timezone: str, value: str | None) -> "DateTimeResolver":
        now = datetime.fromisoformat(value) if value else None
        if now is not None and now.tzinfo is None:
            now = now.replace(tzinfo=ZoneInfo(timezone))
        return cls(timezone, now)

    def resolve_date(self, reference: str | None) -> date:
        if not reference or reference.casefold() == "today":
            return self.now.date()
        try:
            return date.fromisoformat(reference)
        except ValueError as exc:
            raise ValueError(f"Unsupported date reference: {reference}") from exc

    def period_bounds(self, period: str | None) -> tuple[int, int] | None:
        if not period:
            return None
        return PERIODS.get(period.casefold())
