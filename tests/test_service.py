def test_list_status_and_next(service):
    assert len(service.list_today_medications("2026-08-01")) == 3
    assert service.check_dose_status("blood pressure", "2026-08-01")["status"] == "taken"
    assert service.find_next_dose("2026-08-01T10:00:00+05:30")["medication"] == "Vitamin D3 1000 IU"
    assert [x["name"] for x in service.list_today_medications("2026-08-01", (17, 22))] == ["Metformin"]


def test_mark_taken_and_duplicate(service):
    result = service.mark_dose_taken("Vitamin D3", "2026-08-01", "2026-08-01T13:04:00+05:30")
    assert result["status"] == "taken"
    assert service.mark_dose_taken("Vitamin D3", "2026-08-01")["status"] == "already_taken"


def test_instructions_and_history(service):
    assert service.get_saved_instructions("Metformin")["source"] == "synthetic prescription"
    assert len(service.show_medication_history()) == 3
