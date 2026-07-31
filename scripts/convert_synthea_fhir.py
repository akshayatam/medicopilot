#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Support both ``python scripts/convert_synthea_fhir.py`` and module imports.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from medication.normalization import normalize_medication
from medication.reconciliation import detect_conflicts
from medication.validators import calculate_readiness, validate_patient_document

ACTIVE_MEDICATION_STATUSES = {"active", "on-hold"}
SOCIAL_HINTS = ("education", "employment", "criminal record", "housing", "food insecurity", "social isolation", "transportation", "socioeconomic", "income", "literacy", "abuse", "violence", "substance use", "drug use", "alcohol use", "sensitive social")
ADMIN_HINTS = ("medication review", "screening due", "care plan", "assessment due")
HISTORY_HINTS = ("history of", "personal history", "family history")
MEDICATION_PATTERN = re.compile(r"^(?P<name>.+?)\s+(?P<strength>\d+(?:\.\d+)?\s*(?:MG|MCG|G|ML|IU|UNIT(?:S)?))(?:\s+(?P<form>.*))?$", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Convert Synthea FHIR R4 bundles to compact Medication Copilot JSON.")
    p.add_argument("input", type=Path, help="FHIR JSON file or directory")
    p.add_argument("output", type=Path, help="Output file or directory")
    p.add_argument("--min-age", type=int, default=60)
    p.add_argument("--as-of-date", type=date.fromisoformat, default=date.today())
    p.add_argument("--default-timezone", default=None)
    p.add_argument("--include-inactive-medications", action="store_true")
    p.add_argument("--include-all-conditions", action="store_true")
    p.add_argument("--pretty", action="store_true")
    p.add_argument("--old-active-order-days", type=int, default=730)
    return p.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("Top-level JSON must be an object")
    return data


def iter_resources(bundle: dict[str, Any]) -> Iterable[dict[str, Any]]:
    if bundle.get("resourceType") != "Bundle":
        raise ValueError("Expected FHIR Bundle")
    for entry in bundle.get("entry", []):
        if isinstance(entry, dict) and isinstance(entry.get("resource"), dict):
            yield entry["resource"]


def index_resources(resources: Iterable[dict[str, Any]]):
    by_ref: dict[str, dict[str, Any]] = {}
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in resources:
        rt, rid = r.get("resourceType"), r.get("id")
        if isinstance(rt, str):
            by_type[rt].append(r)
        if isinstance(rid, str):
            by_ref[rid] = r
            by_ref[f"urn:uuid:{rid}"] = r
            if isinstance(rt, str):
                by_ref[f"{rt}/{rid}"] = r
    return by_ref, by_type


def calculate_age(birth: date, as_of: date) -> int:
    return as_of.year - birth.year - ((as_of.month, as_of.day) < (birth.month, birth.day))


def parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def parse_dt(value: Any) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def first_coding(obj: Any) -> dict[str, Any]:
    if not isinstance(obj, dict):
        return {"system": None, "code": None, "display": None}
    codings = obj.get("coding")
    if isinstance(codings, list):
        for c in codings:
            if isinstance(c, dict):
                return {"system": c.get("system"), "code": str(c.get("code")) if c.get("code") is not None else None, "display": c.get("display")}
    return {"system": None, "code": None, "display": obj.get("text")}


def coded_status(obj: Any) -> str | None:
    return first_coding(obj)["code"]


def official_name(patient: dict[str, Any]) -> str | None:
    names = [n for n in patient.get("name", []) if isinstance(n, dict)]
    chosen = next((n for n in names if n.get("use") == "official"), names[0] if names else None)
    if not chosen:
        return None
    return " ".join([*(str(x) for x in chosen.get("given", []) if x), str(chosen.get("family")) if chosen.get("family") else ""]).strip() or None


def preferred_language(patient: dict[str, Any]) -> str | None:
    comms = [x for x in patient.get("communication", []) if isinstance(x, dict)]
    comms.sort(key=lambda x: not bool(x.get("preferred")))
    for item in comms:
        c = first_coding(item.get("language"))
        if c["code"] or c["display"]:
            return c["code"] or c["display"]
    return None


def validate_timezone(name: str | None) -> str | None:
    if not name:
        return None
    try:
        ZoneInfo(name)
        return name
    except ZoneInfoNotFoundError as e:
        raise ValueError(f"Invalid IANA timezone: {name}") from e


def patient_summary(patient: dict[str, Any], as_of: date, timezone_name: str | None) -> dict[str, Any]:
    birth = parse_date(patient.get("birthDate"))
    if birth is None:
        raise ValueError("Patient birthDate missing/invalid")
    return {
        "id": patient.get("id"),
        "display_name": official_name(patient),
        "birth_date": birth.isoformat(),
        "age_at_dataset_reference_date": calculate_age(birth, as_of),
        "gender": patient.get("gender"),
        "preferred_language": preferred_language(patient),
        "timezone": validate_timezone(timezone_name),
        "caregiver": None,
        "deceased": bool(patient.get("deceasedBoolean") or patient.get("deceasedDateTime")),
        "source": "Synthea FHIR Patient",
    }


def condition_bucket(display: str | None) -> str:
    text = (display or "").lower()
    if any(x in text for x in HISTORY_HINTS): return "historical_conditions"
    if any(x in text for x in SOCIAL_HINTS): return "social_context"
    if any(x in text for x in ADMIN_HINTS): return "administrative_flags"
    return "clinical_conditions"


def extract_conditions(resources: list[dict[str, Any]], include_all: bool) -> dict[str, list[dict[str, Any]]]:
    out = {"clinical_conditions": [], "historical_conditions": [], "social_context": [], "administrative_flags": []}
    for r in resources:
        c = first_coding(r.get("code"))
        item = {
            "id": r.get("id"), "code_system": c["system"], "code": c["code"], "display": c["display"],
            "clinical_status": coded_status(r.get("clinicalStatus")),
            "verification_status": coded_status(r.get("verificationStatus")),
            "onset": r.get("onsetDateTime") or r.get("onsetDate"),
            "abatement": r.get("abatementDateTime") or r.get("abatementDate"),
            "recorded_date": r.get("recordedDate"), "source": "Synthea FHIR Condition"
        }
        bucket = condition_bucket(item["display"])
        restricted = bucket in {"social_context", "administrative_flags"}
        item["visibility"] = {
            "include_in_medication_context": False,
            "show_in_patient_ui": not restricted,
            "source": "deterministic_condition_visibility_policy",
        }
        if include_all or item["clinical_status"] == "active":
            out[bucket].append(item)
    return out


def extract_allergies(resources: list[dict[str, Any]]):
    if not resources:
        return [], "not_recorded"
    allergies, explicit_none = [], False
    for r in resources:
        c = first_coding(r.get("code")); text = (c["display"] or "").lower(); code = (c["code"] or "").lower()
        if ("no known" in text and "allerg" in text) or code in {"716186003", "no-known-allergy"}:
            explicit_none = True
            continue
        reactions = []
        for reaction in r.get("reaction", []) if isinstance(r.get("reaction"), list) else []:
            manifestations = [first_coding(m)["display"] for m in reaction.get("manifestation", []) if isinstance(m, dict) and first_coding(m)["display"]]
            reactions.append({"manifestations": manifestations, "severity": reaction.get("severity"), "onset": reaction.get("onset")})
        allergies.append({
            "id": r.get("id"), "code_system": c["system"], "code": c["code"], "substance": c["display"],
            "clinical_status": coded_status(r.get("clinicalStatus")), "verification_status": coded_status(r.get("verificationStatus")),
            "type": r.get("type"), "category": r.get("category") if isinstance(r.get("category"), list) else [],
            "criticality": r.get("criticality"), "recorded_date": r.get("recordedDate"), "reactions": reactions,
            "source": "Synthea FHIR AllergyIntolerance"
        })
    if allergies: return allergies, "recorded"
    if explicit_none: return [], "no_known_allergies_explicitly_recorded"
    return [], "not_recorded"


def parse_medication_display(display: str | None):
    if not display: return None, None, None
    m = MEDICATION_PATTERN.match(display.strip())
    return (m.group("name").strip(), m.group("strength").strip(), m.group("form").strip() if m.group("form") else None) if m else (display.strip(), None, None)


def dosage_summary(d: dict[str, Any]) -> dict[str, Any]:
    as_needed = d.get("asNeededBoolean")
    if as_needed is None and d.get("asNeededCodeableConcept") is not None: as_needed = True
    instruction_text = " ".join(str(x or "") for x in (d.get("text"), d.get("patientInstruction"))).casefold()
    if as_needed is None and ("as needed" in instruction_text or "when needed" in instruction_text): as_needed = True
    repeat = ((d.get("timing") or {}).get("repeat") or {}) if isinstance(d.get("timing"), dict) else {}
    exact_times = [str(x) for x in repeat.get("timeOfDay", [])] if isinstance(repeat.get("timeOfDay"), list) else []
    schedules = [] if as_needed is True else [{"time": t, "source": "FHIR dosageInstruction.timing.repeat.timeOfDay", "verified": True} for t in exact_times]
    dose_quantity = None
    for dr in d.get("doseAndRate", []) if isinstance(d.get("doseAndRate"), list) else []:
        q = dr.get("doseQuantity") if isinstance(dr, dict) else None
        if isinstance(q, dict):
            dose_quantity = {"value": q.get("value"), "unit": q.get("unit"), "system": q.get("system"), "code": q.get("code")}; break
    return {
        "sequence": d.get("sequence"), "text": d.get("text"), "patient_instruction": d.get("patientInstruction"),
        "schedule_type": "as_needed" if as_needed is True else ("scheduled" if repeat or d.get("text") else "unknown"),
        "as_needed": as_needed if isinstance(as_needed, bool) else None,
        "frequency": repeat.get("frequency"), "frequency_max": repeat.get("frequencyMax"),
        "period": repeat.get("period"), "period_max": repeat.get("periodMax"), "period_unit": repeat.get("periodUnit"),
        "days_of_week": repeat.get("dayOfWeek") if isinstance(repeat.get("dayOfWeek"), list) else [],
        "exact_times": exact_times, "event_relationships": repeat.get("when") if isinstance(repeat.get("when"), list) else [],
        "bounds": repeat.get("boundsPeriod") if isinstance(repeat.get("boundsPeriod"), dict) else None,
        "dose_quantity": dose_quantity, "route": first_coding(d.get("route"))["display"],
        "method": first_coding(d.get("method"))["display"], "site": first_coding(d.get("site"))["display"],
        "additional_instructions": [first_coding(x)["display"] for x in d.get("additionalInstruction", []) if isinstance(x, dict) and first_coding(x)["display"]] if isinstance(d.get("additionalInstruction"), list) else [],
        "schedule": schedules, "meal_context": None,
        "schedule_guardrail": "No fixed reminder generated because medication is as-needed." if as_needed is True else ("Only exact times explicitly present in FHIR are included." if exact_times else "FHIR contains no exact clock time; no reminder time was invented.")
    }


def medication_reasons(m: dict[str, Any], by_ref: dict[str, dict[str, Any]]):
    out = []
    for rc in m.get("reasonCode", []) if isinstance(m.get("reasonCode"), list) else []:
        c = first_coding(rc); out.append({"reference": None, "code_system": c["system"], "code": c["code"], "display": c["display"]})
    for rr in m.get("reasonReference", []) if isinstance(m.get("reasonReference"), list) else []:
        if not isinstance(rr, dict): continue
        linked = by_ref.get(rr.get("reference")); c = first_coding(linked.get("code")) if linked else {"system": None, "code": None, "display": None}
        out.append({"reference": rr.get("reference"), "code_system": c["system"], "code": c["code"], "display": c["display"] or rr.get("display")})
    return out


def medication_summary(m: dict[str, Any], by_ref: dict[str, dict[str, Any]], as_of: date, old_days: int) -> dict[str, Any]:
    concept = m.get("medicationCodeableConcept") or {}
    medication_reference = m.get("medicationReference") if isinstance(m.get("medicationReference"), dict) else None
    c = first_coding(concept); display = c["display"] or concept.get("text")
    normalized = normalize_medication(concept)
    dosages = [dosage_summary(x) for x in m.get("dosageInstruction", []) if isinstance(x, dict)] if isinstance(m.get("dosageInstruction"), list) else []
    reasons = medication_reasons(m, by_ref)
    dispense = m.get("dispenseRequest") if isinstance(m.get("dispenseRequest"), dict) else {}
    validity = dispense.get("validityPeriod") if isinstance(dispense.get("validityPeriod"), dict) else {}
    requester = m.get("requester") if isinstance(m.get("requester"), dict) else None
    encounter = m.get("encounter") if isinstance(m.get("encounter"), dict) else None
    status = m.get("status")
    flags = list(normalized.pop("validation_flags"))
    if medication_reference and not display: flags.append("unsupported_medication_reference_requires_resolution")
    if not dosages: flags.append("missing_dosage_instruction")
    if not reasons: flags.append("missing_reason")
    if any(x.get("as_needed") is True for x in dosages): flags.append("prn_instruction_requires_review")
    authored = parse_date(m.get("authoredOn"))
    if status in ACTIVE_MEDICATION_STATUSES and authored and (as_of - authored).days > old_days:
        flags.append("old_active_order")
    source_instruction = next((x.get("patient_instruction") or x.get("text") for x in dosages if x.get("patient_instruction") or x.get("text")), None)
    schedules = [s for dosage in dosages for s in dosage.get("schedule", [])]
    return {
        "id": f"med_{m.get('id')}" if m.get("id") else None, "source_ids": [m.get("id")] if m.get("id") else [],
        **normalized,
        "fhir_resource_id": m.get("id"), "medication_reference": medication_reference, "raw_display": display,
        "purpose_labels": [r["display"] for r in reasons if r.get("display")], "reasons": reasons,
        "purpose_source": "linked_fhir_reason" if reasons else "not_recorded",
        "prescription": {"status": status, "intent": m.get("intent"), "authored_on": m.get("authoredOn"),
                         "validity_start": validity.get("start"), "validity_end": validity.get("end"),
                         "requester": {"reference": requester.get("reference"), "display": requester.get("display")} if requester else None,
                         "encounter_reference": encounter.get("reference") if encounter else None},
        "dosage_instructions": dosages,
        "schedule_type": "as_needed" if any(x.get("as_needed") is True for x in dosages) else ("scheduled" if dosages else "unknown"),
        "source_instruction": source_instruction, "source_schedules": schedules,
        "has_exact_reminder_time": bool(schedules), "fhir_status": status, "intent": m.get("intent"),
        "authored_on": m.get("authoredOn"), "current_use_status": "unverified",
        "included_in_daily_plan": False, "reconciliation_status": "needs_review",
        "requires_human_verification": True, "validation_flags": sorted(set(flags)),
        "source": "Synthea FHIR MedicationRequest"
    }


def collapse_renewals(items: list[dict[str, Any]]):
    groups = defaultdict(list)
    for x in items:
        groups[(x.get("code"), (x.get("name") or "").casefold(), (x.get("strength") or "").casefold(), x.get("schedule_type"), (x.get("prescription") or {}).get("status"))].append(x)
    out = []
    for group in groups.values():
        newest = max(group, key=lambda x: parse_dt((x.get("prescription") or {}).get("authored_on")))
        newest["source_ids"] = sorted({sid for g in group for sid in g.get("source_ids", []) if sid})
        newest["renewal_count"] = len(group); out.append(newest)
    return sorted(out, key=lambda x: parse_dt((x.get("prescription") or {}).get("authored_on")), reverse=True)


def convert_bundle(bundle: dict[str, Any], args: argparse.Namespace) -> dict[str, Any] | None:
    by_ref, by_type = index_resources(iter_resources(bundle))
    patients = by_type.get("Patient", [])
    if len(patients) != 1: raise ValueError(f"Expected one Patient resource, found {len(patients)}")
    if parse_date(patients[0].get("birthDate")) is None:
        return None
    patient = patient_summary(patients[0], args.as_of_date, args.default_timezone)
    if patient["age_at_dataset_reference_date"] < args.min_age: return None
    if patient["deceased"]: return None
    conditions = extract_conditions(by_type.get("Condition", []), args.include_all_conditions)
    allergies, allergy_status = extract_allergies(by_type.get("AllergyIntolerance", []))
    meds = [medication_summary(x, by_ref, args.as_of_date, args.old_active_order_days) for x in by_type.get("MedicationRequest", [])]
    # Source orders are never dropped merely because they are inactive. The old
    # CLI switch remains accepted for compatibility but no longer alters source preservation.
    conflicts = detect_conflicts(meds)
    conflict_ids = {mid for flag in conflicts for mid in flag["related_medication_ids"]}
    for med in meds:
        if med["id"] in conflict_ids:
            med["reconciliation_status"] = "needs_review"
    administrations = []
    for resource in by_type.get("MedicationAdministration", []):
        med_ref = resource.get("medicationReference") if isinstance(resource.get("medicationReference"), dict) else {}
        administrations.append({
            "id": resource.get("id"), "medication_reference": med_ref.get("reference"),
            "medication_display": med_ref.get("display"),
            "effective_at": resource.get("effectiveDateTime") or resource.get("effectivePeriod"),
            "status": resource.get("status"),
            "encounter_reference": (resource.get("context") or {}).get("reference") if isinstance(resource.get("context"), dict) else None,
            "source": "Synthea FHIR MedicationAdministration", "eligible_as_home_adherence_log": False,
        })
    result = {
        "schema_version": "2.0",
        "dataset": {"name": "Medication Copilot Synthetic Dataset", "source_dataset": "Synthea FHIR R4", "synthetic": True,
                    "converted_at": datetime.now(timezone.utc).isoformat(), "reference_date": args.as_of_date.isoformat(),
                    "minimum_patient_age": args.min_age,
                    "guardrails": {"absence_of_allergy_resource_means": "not_recorded", "medication_order_is_not_dose_administration": True,
                                   "prn_medications_receive_fixed_schedule": False, "missing_exact_times_are_invented": False,
                                   "family_caregiver_inferred_from_careteam": False}},
        "source_record": {"patient": patient, "medications": meds, "conditions": conditions,
                          "allergies": allergies, "allergy_status": allergy_status,
                          "clinical_administrations": administrations, "reconciliation_flags": conflicts,
                          "import_warnings": sorted({flag for med in meds for flag in med["validation_flags"]}),
                          "source": "Synthea FHIR Bundle",
                          "provenance": {"source_bundle_type": bundle.get("type"), "source": "Synthea FHIR Bundle"}},
        "medication_plan": {"medications": [], "daily_medication_ids": [], "source": "not_reconciled"},
        "dose_logs": [],
        "support_profile": {"caregiver": None, "preferred_response_language": patient.get("preferred_language") or "en-US",
                            "accessibility": {"large_text": True, "high_contrast": True, "voice_enabled": False},
                            "confirmation_style": "explicit", "source": "application_default"},
        "provenance": {"source_bundle_type": bundle.get("type"), "source_resource_counts": {k: len(v) for k, v in sorted(by_type.items())},
                       "resources_used": ["Patient", "MedicationRequest", "Condition", "AllergyIntolerance", "MedicationAdministration"],
                       "resources_not_used_for_medication_copilot": sorted(set(by_type) - {"Patient", "MedicationRequest", "Condition", "AllergyIntolerance", "MedicationAdministration"})}
    }
    result["import_summary"] = calculate_readiness(result)
    validate_patient_document(result)
    return result


def discover(path: Path):
    if path.is_file(): return [path]
    if path.is_dir(): return sorted(path.rglob("*.json"))
    raise ValueError(f"Input does not exist: {path}")


def main() -> int:
    args = parse_args(); validate_timezone(args.default_timezone)
    files = discover(args.input)
    if args.input.is_dir(): args.output.mkdir(parents=True, exist_ok=True)
    converted = skipped = skipped_non_patient = failed = 0
    for src in files:
        try:
            bundle = load_json(src)
            if args.input.is_dir() and not any(
                resource.get("resourceType") == "Patient"
                for resource in iter_resources(bundle)
            ):
                skipped_non_patient += 1
                print(f"SKIP non-patient bundle: {src}", file=sys.stderr)
                continue
            result = convert_bundle(bundle, args)
            if result is None:
                skipped += 1; print(f"SKIP age<{args.min_age}: {src}", file=sys.stderr); continue
            dest = args.output if args.input.is_file() else args.output / src.relative_to(args.input).with_name(src.stem + ".medication-copilot.json")
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2 if args.pretty else None, separators=None if args.pretty else (",", ":")); f.write("\n")
            converted += 1; print(f"WROTE: {dest}")
        except Exception as e:
            failed += 1; print(f"ERROR {src}: {e}", file=sys.stderr)
    print(
        f"Summary: converted={converted}, skipped_age={skipped}, "
        f"skipped_non_patient={skipped_non_patient}, failed={failed}",
        file=sys.stderr,
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
