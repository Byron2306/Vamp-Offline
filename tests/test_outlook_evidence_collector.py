from backend.outlook_evidence_collector import (
    _extract_row_date_from_text,
    _match_candidate_to_plans,
    _search_query_for_plan,
    _search_queries_for_plan,
)


def test_teaching_module_search_pairs_code_with_evidence_noun():
    plan = {
        "task_id": "task_004",
        "kpa_code": "KPA1",
        "title": "Jan: Assessment planning & rubric development - HISE312 (100 students)",
        "keywords": ["assessment", "rubric", "marking", "criteria", "HISE312"],
    }

    assert _search_query_for_plan(plan) == "HISE312 rubric"


def test_teaching_plan_gets_a_small_set_of_specific_queries():
    plan = {
        "task_id": "task_017",
        "kpa_code": "KPA1",
        "title": "Year-end marks and moderation - HISE312 (100 students)",
        "keywords": ["moderation", "marks", "exam", "final", "HISE312"],
    }

    assert _search_queries_for_plan(plan)[:2] == ["HISE312 marks", "HISE312 moderation"]


def test_candidate_requires_real_evidence_signal_not_generic_overlap():
    plans = [
        {
            "task_id": "task_006",
            "kpa_code": "KPA1",
            "title": "Semester 1 Teaching: HISE312 (100 students)",
            "keywords": ["lecture", "assessment", "student", "class", "HISE312"],
        }
    ]

    task_ids, _, _, matched = _match_candidate_to_plans(
        month_bucket="2026-03",
        candidate_text="Regular academic progress meeting about student support for the semester",
        attachment_names=[],
        received_at="2026-03-14T09:00:00Z",
        plans=plans,
    )

    assert task_ids == []
    assert matched == []


def test_short_outlook_row_date_uses_target_year():
    assert _extract_row_date_from_text("Tue 5/5 HISE312 announcement", "2026-02") == "2026-05-05"


def test_candidate_matches_module_plus_attachment_artifact():
    plans = [
        {
            "task_id": "task_017",
            "kpa_code": "KPA1",
            "title": "Semester 1 marks submission deadline - HISE312 (100 students)",
            "keywords": ["marks", "gradebook", "submission", "assessment", "HISE312"],
        }
    ]

    task_ids, kpa, reason, matched = _match_candidate_to_plans(
        month_bucket="2026-06",
        candidate_text="HISE312 final marks submitted for moderation",
        attachment_names=["HISE312_gradebook_moderation.xlsx"],
        received_at="2026-06-20T10:15:00Z",
        plans=plans,
    )

    assert task_ids == ["task_017"]
    assert kpa == "KPA1"
    assert "gradebook" in matched[0]["matched_terms"]
    assert "evidence signals" in reason


def test_out_of_month_candidate_is_rejected():
    plans = [
        {
            "task_id": "task_030",
            "kpa_code": "KPA3",
            "title": "Conference: GBL conference",
            "keywords": ["conference", "presentation", "acceptance", "GBL"],
        }
    ]

    task_ids, _, _, _ = _match_candidate_to_plans(
        month_bucket="2026-04",
        candidate_text="GBL conference presentation accepted",
        attachment_names=["acceptance_letter.pdf"],
        received_at="2026-05-01T08:00:00Z",
        plans=plans,
    )

    assert task_ids == []
