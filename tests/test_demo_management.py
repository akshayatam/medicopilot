import hashlib
import json
from pathlib import Path

import pytest

from scripts import demo_management
from scripts.demo_management import reset_demo, verify_demo


class HealthyClient:
    base_url = "http://localhost:11434"
    model = "gemma4:e2b"

    def health_check(self):
        return {"reachable": True, "model_available": True, "generation_ok": True}


class OfflineClient(HealthyClient):
    def health_check(self):
        return {"reachable": False, "model_available": False, "generation_ok": False, "error": "offline"}


def digest(directory: Path) -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.glob("*.runtime.json"))
    }


def test_reset_is_deterministic_and_replaces_complete_directory(tmp_path):
    runtime = tmp_path / "runtime_patients"
    runtime.mkdir()
    (runtime / "stale.runtime.json").write_text("{}", encoding="utf-8")
    first = reset_demo(runtime)
    first_digest = digest(runtime)
    second = reset_demo(runtime)
    assert first["patient_ids"] == second["patient_ids"] == ["demo-ready-001", "demo-unready-001"]
    assert first_digest == digest(runtime)
    assert set(first_digest) == {"ready.runtime.json", "unready.runtime.json"}


def test_failed_generation_preserves_existing_runtime(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime_patients"
    runtime.mkdir()
    existing = runtime / "existing.runtime.json"
    existing.write_text('{"sentinel": true}', encoding="utf-8")

    def fail(_output):
        raise RuntimeError("generation failed")

    monkeypatch.setattr(demo_management, "prepare_demo_data", fail)
    with pytest.raises(RuntimeError, match="generation failed"):
        reset_demo(runtime)
    assert json.loads(existing.read_text(encoding="utf-8")) == {"sentinel": True}


def test_verify_accepts_offline_model_unless_required(tmp_path):
    runtime = tmp_path / "runtime_patients"
    reset_demo(runtime)
    normal = verify_demo(OfflineClient(), runtime, "2026-08-01T10:00:00-04:00")
    strict = verify_demo(OfflineClient(), runtime, None, require_model=True)
    assert normal["status"] == "ok" and normal["data_valid"] and normal["warnings"]
    assert strict["status"] == "failed" and strict["data_valid"]


def test_verify_reports_all_required_checks(tmp_path):
    runtime = tmp_path / "runtime_patients"
    reset_demo(runtime)
    report = verify_demo(HealthyClient(), runtime, "2026-08-01T10:00:00-04:00")
    assert report["status"] == "ok"
    assert all(check["ok"] for check in report["checks"])
    assert report["model"]["minimal_generation_succeeds"]
