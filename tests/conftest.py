import json
from pathlib import Path

import pytest

from medication.repository import MedicationRepository
from medication.service import MedicationService


@pytest.fixture
def data_path(tmp_path: Path) -> Path:
    source = Path(__file__).parents[1] / "data" / "synthetic_patient.json"
    target = tmp_path / "patient.json"
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return target


@pytest.fixture
def repository(data_path):
    return MedicationRepository(data_path)


@pytest.fixture
def service(repository):
    return MedicationService(repository)
