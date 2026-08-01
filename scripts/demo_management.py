"""Safe reset and verification workflows for the curated local demo."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from gemma.client import OllamaClient
from medication.patient_data_service import PatientDataService
from medication.schemas import ReconciliationProfile
from scripts.prepare_demo_data import ROOT, prepare_demo_data

EXPECTED_PATIENTS = {
    "ready.runtime.json": "demo-ready-001",
    "unready.runtime.json": "demo-unready-001",
}
PROTECTED_RELATIVE_PATHS = (
    "data/reconciliation/ready_demo.json",
    "data/reconciliation/unready_demo.json",
    "data/runtime_patients/ready.runtime.json",
    "data/runtime_patients/unready.runtime.json",
    "data/evaluation_cases.jsonl",
    "data/synthetic_patient.json",
    "rules.md",
)


def _validate_generated(directory: Path) -> PatientDataService:
    service = PatientDataService(directory)
    if service.validation_errors:
        raise ValueError(f"Generated runtime schema validation failed: {service.validation_errors}")
    by_file = {summary.path.name: summary.patient_id for summary in service.list_available_patients()}
    if by_file != EXPECTED_PATIENTS:
        raise ValueError(f"Generated patients did not match expected demo set: {by_file}")
    if not any(summary.ready for summary in service.list_available_patients()):
        raise ValueError("Generated demo has no ready patient")
    if not any(not summary.ready for summary in service.list_available_patients()):
        raise ValueError("Generated demo has no unready patient")
    return service


def reset_demo(runtime_directory: Path) -> dict[str, Any]:
    """Stage, validate, and atomically install deterministic runtime patients."""
    runtime_directory = runtime_directory.resolve()
    runtime_directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="medicopilot-demo-", dir=runtime_directory.parent) as temporary:
        staging = Path(temporary) / "runtime_patients"
        generated = prepare_demo_data(staging)
        service = _validate_generated(staging)

        backup = Path(temporary) / "previous-runtime"
        had_previous = runtime_directory.exists()
        if had_previous:
            os.replace(runtime_directory, backup)
        try:
            os.replace(staging, runtime_directory)
        except Exception:
            if had_previous and backup.exists():
                os.replace(backup, runtime_directory)
            raise

    return {
        "status": "ok",
        "runtime_directory": str(runtime_directory),
        "patients_generated": len(generated),
        "patient_ids": sorted(summary.patient_id for summary in service.list_available_patients()),
        "ready_patients": sum(summary.ready for summary in service.list_available_patients()),
        "unready_patients": sum(not summary.ready for summary in service.list_available_patients()),
    }


def _check(checks: list[dict[str, Any]], name: str, ok: bool, detail: Any) -> None:
    checks.append({"name": name, "ok": bool(ok), "detail": detail})


def verify_demo(
    client: OllamaClient,
    runtime_directory: Path,
    demo_now: str | None,
    *,
    require_model: bool = False,
    project_root: Path = ROOT,
) -> dict[str, Any]:
    """Validate repository demo assets and optionally require local Gemma health."""
    checks: list[dict[str, Any]] = []
    runtime_directory = runtime_directory.resolve()
    _check(checks, "runtime_directory_exists", runtime_directory.is_dir(), str(runtime_directory))
    missing_runtime = [name for name in EXPECTED_PATIENTS if not (runtime_directory / name).is_file()]
    _check(checks, "expected_runtime_files", not missing_runtime, missing_runtime or "present")

    patients = PatientDataService(runtime_directory)
    summaries = patients.list_available_patients()
    _check(checks, "runtime_schemas_validate", not patients.validation_errors and bool(summaries), patients.validation_errors or f"{len(summaries)} valid")
    ids = [summary.patient_id for summary in summaries]
    _check(checks, "patient_ids_unique", len(ids) == len(set(ids)), ids)
    expected_ids = set(EXPECTED_PATIENTS.values())
    _check(checks, "expected_patient_ids", set(ids) == expected_ids, ids)
    _check(checks, "ready_patient_exists", any(summary.ready for summary in summaries), [s.patient_id for s in summaries if s.ready])
    _check(checks, "unready_patient_exists", any(not summary.ready for summary in summaries), [s.patient_id for s in summaries if not s.ready])

    profile_errors: dict[str, str] = {}
    for name in ("ready_demo.json", "unready_demo.json"):
        path = project_root / "data" / "reconciliation" / name
        try:
            ReconciliationProfile.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as exc:
            profile_errors[name] = str(exc)
    _check(checks, "reconciliation_profiles_validate", not profile_errors, profile_errors or "2 valid")

    ready = [patients.load_patient(s.patient_id) for s in summaries if s.ready]
    unready = [patients.load_patient(s.patient_id) for s in summaries if not s.ready]
    confirmed = [m for p in ready for m in p.medication_plan.medications if m.included_in_daily_plan and m.current_use_status == "confirmed_current"]
    _check(checks, "ready_has_confirmed_medications", bool(confirmed), len(confirmed))
    schedules_ok = bool(confirmed) and all(m.reminder_schedule and all(schedule.verified for schedule in m.reminder_schedule) for m in confirmed)
    _check(checks, "ready_has_verified_schedules", schedules_ok, sum(len(m.reminder_schedule) for m in confirmed))
    dose_refs_ok = all(log.medication_id in {m.id for m in p.medication_plan.medications} for p in ready + unready for log in p.dose_logs)
    _check(checks, "dose_logs_reference_plan", dose_refs_ok, "valid" if dose_refs_ok else "invalid reference")
    blocked = bool(unready) and all(not p.import_summary.ready_for_medication_tracking and bool(p.import_summary.blocking_issues) for p in unready)
    _check(checks, "unready_patient_blocked", blocked, [p.import_summary.blocking_issues for p in unready])
    _check(checks, "timezones_validate", bool(summaries) and not patients.validation_errors, [s.timezone for s in summaries])

    missing_protected = [relative for relative in PROTECTED_RELATIVE_PATHS if not (project_root / relative).is_file()]
    _check(checks, "protected_files_exist", not missing_protected, missing_protected or "present")
    active_clock = demo_now or "system_clock_per_patient_timezone"
    _check(checks, "active_demo_clock_displayed", bool(active_clock), active_clock)

    model = client.health_check()
    model_ok = bool(model.get("reachable") and model.get("model_available") and model.get("generation_ok"))
    data_ok = all(item["ok"] for item in checks)
    warnings = [] if model_ok else ["Local Ollama/Gemma generation is unavailable; deterministic demo data remains valid."]
    return {
        "status": "ok" if data_ok and (model_ok or not require_model) else "failed",
        "data_valid": data_ok,
        "require_model": require_model,
        "active_demo_clock": active_clock,
        "checks": checks,
        "model": {
            "endpoint": client.base_url,
            "configured_model": client.model,
            "ollama_reachable": bool(model.get("reachable")),
            "model_available": bool(model.get("model_available")),
            "minimal_generation_succeeds": bool(model.get("generation_ok")),
            "error": model.get("error"),
        },
        "warnings": warnings,
    }
