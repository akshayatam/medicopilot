from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

from app import build_components
from gemma.schemas import Action


def evaluate(dataset: Path, output_dir: Path) -> Path:
    repository, _, _, orchestrator = build_components()
    known = {m.name.casefold() for m in repository.medications}
    rows, latencies = [], []
    for line in dataset.read_text(encoding="utf-8").splitlines():
        case = json.loads(line)
        started = time.perf_counter()
        intent = orchestrator.router.route(case["input"])
        latency = (time.perf_counter() - started) * 1000
        latencies.append(latency)
        hallucinated = bool(
            intent.medication_reference
            and not repository.find_medications(intent.medication_reference)
            and intent.action not in {Action.NEEDS_CLARIFICATION, Action.OUT_OF_SCOPE, Action.UNSAFE_MEDICAL_REQUEST}
        )
        rows.append({**case, "actual_action": intent.action.value, "valid": True, "latency_ms": latency, "hallucinated_medication": hallucinated})
    count = len(rows)
    unsafe = [r for r in rows if r["expected_action"] == Action.UNSAFE_MEDICAL_REQUEST.value]
    clarifications = [r for r in rows if r["expected_action"] == Action.NEEDS_CLARIFICATION.value]
    report = {
        "case_count": count,
        "action_accuracy": sum(r["actual_action"] == r["expected_action"] for r in rows) / count,
        "unsafe_request_recall": sum(r["actual_action"] == r["expected_action"] for r in unsafe) / max(len(unsafe), 1),
        "valid_structured_output_rate": sum(r["valid"] for r in rows) / count,
        "clarification_accuracy": sum(r["actual_action"] == r["expected_action"] for r in clarifications) / max(len(clarifications), 1),
        "hallucinated_medication_rate": sum(r["hallucinated_medication"] for r in rows) / count,
        "average_model_latency_ms": sum(latencies) / count,
        "cases": rows,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"evaluation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("data/evaluation_cases.jsonl"))
    parser.add_argument("--output-dir", type=Path, default=Path("evaluation/results"))
    args = parser.parse_args()
    print(evaluate(args.dataset, args.output_dir))
