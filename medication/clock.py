from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from zoneinfo import ZoneInfo


class Clock(ABC):
    @abstractmethod
    def now(self) -> datetime: ...


class SystemClock(Clock):
    def __init__(self, timezone: str) -> None:
        self.timezone = ZoneInfo(timezone)

    def now(self) -> datetime:
        return datetime.now(self.timezone)


class FixedClock(Clock):
    def __init__(self, value: str | datetime) -> None:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("fixed clock timestamp must include a timezone offset")
        self.value = parsed

    def now(self) -> datetime:
        return self.value

