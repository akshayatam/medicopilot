def test_loads_synthetic_patient(repository):
    assert repository.patient.display_name == "Anita Sharma"
    assert len(repository.medications) == 3


def test_lookup_exact_strength_and_purpose(repository):
    assert repository.find_medication("Amlodipine 5 mg").id == "med_amlodipine"
    assert repository.find_medication("blood pressure medicine").id == "med_amlodipine"


def test_ambiguous_lookup_does_not_guess(repository):
    assert repository.find_medication("medicine") is None
