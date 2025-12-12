from backend.contracts import task_agreement_import
from backend.staff_profile import StaffProfile


def test_ta_import_attaches_context_and_flags(monkeypatch, tmp_path):
    profile = StaffProfile(
        staff_id="tester1",
        name="Test User",
        position="Lecturer",
        cycle_year=2024,
        faculty="",
        line_manager="",
    )

    fake_summary = {
        "kpa_summary": {
            "KPA1": {"name": "Teaching and Learning", "hours": 100.0, "weight_pct": 40.0},
            "KPA3": {"name": "Research", "hours": 50.0, "weight_pct": 20.0},
        },
        "teaching": ["Teach ABC123"],
        "supervision": ["Supervise 2 MEd"],
        "research": ["Publish article"],
        "leadership": ["Committee work"],
        "social": ["Community outreach"],
        "norm_hours": 1728.0,
    }

    monkeypatch.setattr(
        task_agreement_import,
        "parse_task_agreement",
        lambda path, director_level=False: fake_summary,
    )

    ta_path = tmp_path / "ta.xlsx"
    ta_path.write_text("stub")

    updated = task_agreement_import.import_task_agreement_excel(profile, ta_path)

    kpa_map = {k.code: k for k in updated.kpas}
    assert kpa_map["KPA1"].ta_context["teaching"] == ["Teach ABC123"]
    assert kpa_map["KPA1"].ta_context["supervision"] == ["Supervise 2 MEd"]
    assert kpa_map["KPA3"].ta_context["research"] == ["Publish article"]
    assert updated.flags == ["TA_IMPORTED"]

    # TA import should not create KPIs
    assert all(not kpa.kpis for kpa in updated.kpas)

