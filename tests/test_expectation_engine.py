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
