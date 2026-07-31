from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from config import settings
from gemma.client import OllamaClient, OllamaError
from gemma.intent_router import IntentRouter
from gemma.orchestrator import MedicationOrchestrator
from gemma.response_parser import IntentParseError
from medication.repository import MedicationRepository
from medication.schemas import UserInput
from medication.service import MedicationService
from medication.clock import FixedClock, SystemClock
from medication.health import ApplicationHealthService
from medication.patient_data_service import PatientDataService
from medication.runtime_service import RuntimeMedicationService


def build_components() -> tuple[MedicationRepository, MedicationService, OllamaClient, MedicationOrchestrator]:
    repository = MedicationRepository(settings.data_file)
    service = MedicationService(repository)
    client = OllamaClient(settings.ollama_base_url, settings.ollama_model, settings.ollama_timeout_seconds)
    return repository, service, client, MedicationOrchestrator(service, IntentRouter(client))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local synthetic medication copilot.")
    commands = parser.add_subparsers(dest="command", required=True)
    today = commands.add_parser("today"); today.add_argument("--date", required=True)
    status = commands.add_parser("status"); status.add_argument("medicine"); status.add_argument("--date", required=True)
    nxt = commands.add_parser("next"); nxt.add_argument("--now", required=True)
    mark = commands.add_parser("mark-taken"); mark.add_argument("medicine"); mark.add_argument("--date", required=True); mark.add_argument("--taken-at")
    instructions = commands.add_parser("instructions"); instructions.add_argument("medicine")
    history = commands.add_parser("history"); history.add_argument("medicine", nargs="?")
    ask = commands.add_parser("ask"); ask.add_argument("question"); ask.add_argument("--now"); ask.add_argument("--patient")
    commands.add_parser("health")
    serve = commands.add_parser("serve"); serve.add_argument("--now")
    convert = commands.add_parser("convert-fhir"); convert.add_argument("input"); convert.add_argument("output"); convert.add_argument("--min-age", type=int, default=60); convert.add_argument("--as-of-date", type=date.fromisoformat, default=date.today()); convert.add_argument("--default-timezone"); convert.add_argument("--old-active-order-days", type=int, default=730); convert.add_argument("--pretty", action="store_true"); convert.add_argument("--include-inactive-medications", action="store_true"); convert.add_argument("--include-all-conditions", action="store_true")
    inspect = commands.add_parser("inspect-patient"); inspect.add_argument("patient")
    reconcile = commands.add_parser("reconcile-patient"); reconcile.add_argument("patient"); reconcile.add_argument("reconciliation"); reconcile.add_argument("output", nargs="?")
    plan = commands.add_parser("build-plan"); plan.add_argument("patient"); plan.add_argument("reconciliation"); plan.add_argument("output")
    logs = commands.add_parser("generate-dose-logs"); logs.add_argument("plan"); logs.add_argument("--days", type=int, required=True); logs.add_argument("--seed", type=int, required=True); logs.add_argument("--start-date", type=date.fromisoformat, default=date.today()); logs.add_argument("--output")
    validate = commands.add_parser("validate-patient"); validate.add_argument("patient")
    readiness = commands.add_parser("readiness"); readiness.add_argument("patient")
    commands.add_parser("list-patients")
    patient_status = commands.add_parser("patient-status"); patient_status.add_argument("patient_id")
    return parser


def _read(path: str) -> dict:
    with Path(path).open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("JSON document must be an object")
    return value


def _write(path: str, value: dict) -> None:
    with Path(path).open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "convert-fhir":
        from scripts.convert_synthea_fhir import main as converter_main
        import sys
        converter_args = [args.input, args.output, "--min-age", str(args.min_age), "--as-of-date", args.as_of_date.isoformat(), "--old-active-order-days", str(args.old_active_order_days)]
        if args.default_timezone: converter_args += ["--default-timezone", args.default_timezone]
        if args.pretty: converter_args.append("--pretty")
        if args.include_all_conditions: converter_args.append("--include-all-conditions")
        old_argv = sys.argv
        try:
            sys.argv = [old_argv[0], *converter_args]
            raise SystemExit(converter_main())
        finally:
            sys.argv = old_argv
    if args.command in {"inspect-patient", "validate-patient", "readiness", "reconcile-patient", "build-plan", "generate-dose-logs"}:
        from medication.adherence_simulator import simulate_adherence
        from medication.plan_builder import build_plan, generate_scheduled_doses
        from medication.reconciliation import apply_reconciliation
        from medication.validators import calculate_readiness, validate_patient_document
        source_path = args.plan if args.command == "generate-dose-logs" else args.patient
        document = _read(source_path)
        if args.command == "inspect-patient": result = {"schema_version": document.get("schema_version"), "patient": document.get("source_record", {}).get("patient"), "import_summary": document.get("import_summary"), "source_medication_count": len(document.get("source_record", {}).get("medications", document.get("source_record", {}).get("medication_requests", []))), "plan_medication_count": len(document.get("medication_plan", {}).get("medications", [])), "dose_log_count": len(document.get("dose_logs", []))}
        elif args.command == "validate-patient": validate_patient_document(document); result = {"valid": True}
        elif args.command == "readiness": result = calculate_readiness(document)
        elif args.command in {"reconcile-patient", "build-plan"}:
            document = apply_reconciliation(document, _read(args.reconciliation)); document = build_plan(document); document["import_summary"] = calculate_readiness(document)
            output = args.output or args.patient
            _write(output, document); result = {"output": output, "import_summary": document["import_summary"]}
        else:
            scheduled = generate_scheduled_doses(document, args.start_date, args.days)
            document["dose_logs"] = simulate_adherence(scheduled, args.seed)
            output = args.output or args.plan
            validate_patient_document(document); _write(output, document); result = {"output": output, "dose_logs_generated": len(document["dose_logs"]), "seed": args.seed}
        print(json.dumps(result, indent=2, ensure_ascii=False)); return
    client = OllamaClient(settings.ollama_base_url, settings.ollama_model, settings.ollama_timeout_seconds)
    patients = PatientDataService(settings.runtime_patients_directory)
    if args.command == "list-patients":
        print(json.dumps([p.model_dump(mode="json", exclude={"path"}) | {"label": p.label} for p in patients.list_available_patients()], indent=2)); return
    if args.command == "patient-status":
        patient = patients.load_patient(args.patient_id)
        print(json.dumps({"patient": patient.source_record.patient.model_dump(mode="json"), "readiness": patient.import_summary.model_dump(mode="json"), "confirmed_medication_count": len([m for m in patient.medication_plan.medications if m.included_in_daily_plan]), "allergy_status": patient.source_record.allergy_status}, indent=2)); return
    if args.command == "ask":
        selected_patient = args.patient or next((p.patient_id for p in patients.list_available_patients() if p.ready), None)
        if not selected_patient:
            raise SystemExit("Error: No ready runtime patient is available.")
        patient = patients.load_patient(selected_patient)
        clock = FixedClock(args.now or settings.demo_now) if (args.now or settings.demo_now) else SystemClock(patient.source_record.patient.timezone)
        service = RuntimeMedicationService(patients, selected_patient, clock)
        orchestrator = MedicationOrchestrator(service, IntentRouter(client))
        try: result = orchestrator.handle(UserInput(text=args.question)).as_dict()
        except (OllamaError, IntentParseError) as exc: result = {"response": "I could not route that request safely, so no medication action was performed.", "action": "ROUTING_ERROR", "tool_output": None, "errors": [str(exc)], "active_clock": clock.now().isoformat(), "outcome": "routing_error"}
        print(json.dumps(result, indent=2, ensure_ascii=False)); return
    repository, service, _, orchestrator = build_components()
    try:
        if args.command == "today": result = service.list_today_medications(args.date)
        elif args.command == "status": result = service.check_dose_status(args.medicine, args.date)
        elif args.command == "next": result = service.find_next_dose(args.now)
        elif args.command == "mark-taken": result = service.mark_dose_taken(args.medicine, args.date, args.taken_at)
        elif args.command == "instructions": result = service.get_saved_instructions(args.medicine)
        elif args.command == "history": result = service.show_medication_history(args.medicine)
        elif args.command == "health": result = ApplicationHealthService(client, patients, settings.demo_now).check()
        elif args.command == "ask":
            result = orchestrator.handle(UserInput(text=args.question), args.now or settings.demo_now).as_dict()
        elif args.command == "serve":
            from ui.gradio_app import create_app
            create_app(client, settings.runtime_patients_directory, settings.demo_now).launch(
                server_name="127.0.0.1", server_port=7860, share=False
            )
            return
        else: raise RuntimeError(f"Unsupported command: {args.command}")
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except (ValueError, FileNotFoundError, OllamaError, IntentParseError) as exc:
        raise SystemExit(f"Error: {exc}") from exc


if __name__ == "__main__":
    main()
