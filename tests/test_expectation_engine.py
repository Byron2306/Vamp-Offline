from pathlib import Path

from backend.expectation_engine import parse_task_agreement


def test_addendum_b_modules_are_attached_to_kpa2():
    excel_path = Path("Bunt B 2026 FEDU_Task_Agreement_Form (5).xlsx")

    summary = parse_task_agreement(str(excel_path))
    kpa2 = summary.get("kpa_summary", {}).get("KPA2")

    assert kpa2 is not None, "KPA2 context should be present when modules are found"
    assert kpa2.get("teaching_modules") == [
        "BSTE312",
        "BSTE412",
        "BSTE322",
        "BSTE422",
        "BSTD512",
        "LABD522",
    ]


def test_teaching_practice_windows_are_bucketed_and_not_in_kpis():
    excel_path = Path("Bunt B 2026 FEDU_Task_Agreement_Form (5).xlsx")

    summary = parse_task_agreement(str(excel_path))

    assert "April" in summary.get("teaching_practice_windows", [])
    assert "July" in summary.get("teaching_practice_windows", [])
    assert not any(
        token in item
        for item in summary.get("teaching", [])
        for token in ("April", "July")
    )


def test_supervision_rows_are_classified_and_reported():
    excel_path = Path("Bunt B 2026 FEDU_Task_Agreement_Form (5).xlsx")

    summary = parse_task_agreement(str(excel_path))
    section2_report = summary.get("ta_parse_report", {}).get(2, {})

    assert any("Maarman" in s for s in summary.get("supervision", []))
    assert not any("Maarman" in t for t in summary.get("teaching", []))
    assert section2_report
    assert section2_report.get("rows_unconsumed", 0) < section2_report.get(
        "rows_consumed", 0
    )
