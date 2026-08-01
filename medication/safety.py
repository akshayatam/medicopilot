from __future__ import annotations

import re
from dataclasses import dataclass

STANDARD_REFUSAL = (
    "I can help you review your saved medication schedule and dose history, "
    "but I cannot recommend changes to medication or provide treatment advice. "
    "Please contact a clinician, pharmacist, or emergency service as appropriate."
)
EMERGENCY_REFUSAL = (
    "This may be an emergency. I cannot assess or treat an overdose, accidental "
    "ingestion, or severe symptoms. Contact local emergency services or poison "
    "control now. Do not rely on this app for urgent guidance."
)

_EMERGENCY = (
    r"\boverdos(?:e|ed|ing)\b", r"accidental(?:ly)? (?:took|swallowed|ingestion)",
    r"\bpoison(?:ed|ing)?\b", r"\bcan'?t breathe\b", r"\bunconscious\b",
    r"\bबहुत ज़्यादा\b",
)
_UNSAFE = (
    r"\b(double|increase|decrease|change|reduce) (?:my |the )?(?:dose|dosage)",
    r"\b(two|2) (?:tablets|pills|doses)\b", r"\bskip (?:my |the )?(?:dose|pill)",
    r"\btake (?:two|2) today\b",
    r"\bstop (?:taking )?", r"\breplace .+ with\b", r"\boverride\b",
    r"\b(interaction|interact)\b", r"\b(combine|mix|together)\b",
    r"\bwhat (?:medicine|medication|pill) (?:should|can) i take\b",
    r"\bis .+ safe (?:for|with)\b", r"\bdiagnos", r"\btreatment\b", r"\bprescrib",
    r"\bshould i take\b", r"\bक्या .* (?:खाऊं|लूं)\b",
    r"\bi missed .*(?:dose|pill|tablet|medicine|medication).*(?:what|should)\b",
    r"\bwhat should i do.*missed\b", r"\bhow much insulin\b",
    r"\bदोगुनी\b", r"\bband kar\b", r"\bdouble (?:kar|le|dose)\b",
)


@dataclass(frozen=True)
class SafetyResult:
    unsafe: bool
    emergency: bool = False
    reason: str | None = None
    response: str | None = None


def check_safety(text: str) -> SafetyResult:
    normalized = " ".join(text.casefold().split())
    if any(re.search(pattern, normalized) for pattern in _EMERGENCY):
        return SafetyResult(True, True, "Emergency or ingestion language", EMERGENCY_REFUSAL)
    if any(re.search(pattern, normalized) for pattern in _UNSAFE):
        return SafetyResult(True, False, "Medical advice or medication change request", STANDARD_REFUSAL)
    return SafetyResult(False)
