import json

import pytest

from backend.batch7_scorer import (
    Artefact,
    ContractSummary,
    EvidenceClassification,
    KPAContract,
    KPIContract,
    MatchedKPI,
    ScoringContext,
    score_artefact,
)


def _contract_with_kpi(kpa_code: str = "KPA1", kpi_id: str = "T1") -> ContractSummary:
    kpi = KPIContract(
        kpi_id=kpi_id,
        kpi="Set exam papers",
        measure="Exam papers submitted",
        target="2",
        evidence_types=["Exam paper"],
    )
    kpa = KPAContract(code=kpa_code, name="Teaching and Learning", weight_pct=40.0, kpis=[kpi])
    return ContractSummary(staff_no="12345", year=2025, post_level="Senior", kpas=[kpa])


def _base_context(text: str = "Final exam paper") -> ScoringContext:
    artefact = Artefact(
        filename="exam.docx",
        extension=".docx",
        extracted_text=text,
        extract_status="ok",
        extract_error=None,
    )
    classification = EvidenceClassification(
        evidence_type="Exam paper",
        category="Teaching",
        credibility_weight=0.9,
    )
    return ScoringContext(
        artefact=artefact,
        evidence_classification=classification,
        contract_summary=_contract_with_kpi(),
    )


def _pass_a_response(claims: list, confidence: float = 0.9, evidence_type: str = "Exam paper") -> str:
    return json.dumps(
        {
            "evidence_type": evidence_type,
            "claims": claims,
            "identified_modules": ["BSTE312"],
            "confidence": confidence,
        }
    )


def _pass_b_response(
    matched_kpis: list,
    completion: float = 0.7,
    rating: int = 4,
    tier: str = "Transformational",
    impact: str = "",
    confidence: float = 0.8,
) -> str:
    return json.dumps(
        {
            "matched_kpis": matched_kpis,
            "completion_estimate": completion,
            "recommended_rating": rating,
            "recommended_tier": tier,
            "impact_summary": impact,
            "confidence": confidence,
        }
    )


def test_exam_paper_maps_to_teaching_kpi():
    ctx = _base_context("Final exam paper for teaching module")

    def pass_a(_prompt: str) -> str:
        return _pass_a_response([{"claim": "Exam paper prepared", "quantifier": 1, "timeframe": "2025"}])

    def pass_b(_prompt: str) -> str:
        return _pass_b_response(
            [{"kpa_code": "KPA1", "kpi_id": "T1", "match_strength": 0.9, "justification": "Exam paper"}],
            completion=0.75,
            impact="Covers exam paper",
        )

    score = score_artefact(ctx, pass_a_llm=pass_a, pass_b_llm=pass_b)

    assert score.status == "SCORED"
    assert score.matched_kpis and score.matched_kpis[0].kpi_id == "T1"
    assert "KPA1" in score.kpa_codes


def test_screenshot_low_credibility_needs_review():
    ctx = _base_context("Screenshot evidence")
    ctx.evidence_classification.credibility_weight = 0.2
    ctx.evidence_classification.evidence_type = "Screenshot"

    def pass_a(_prompt: str) -> str:
        return _pass_a_response([{"claim": "Screenshot of dashboard", "quantifier": None, "timeframe": None}])

    def pass_b(_prompt: str) -> str:
        return _pass_b_response(
            [{"kpa_code": "KPA1", "kpi_id": "T1", "match_strength": 0.5, "justification": "dashboard"}],
            completion=0.8,
            impact="Dashboard screenshot",
        )

    score = score_artefact(ctx, pass_a_llm=pass_a, pass_b_llm=pass_b)

    assert score.status == "NEEDS_REVIEW"
    assert score.completion_estimate <= 0.4
    assert "Low-credibility" in score.impact_summary


def test_empty_text_needs_review():
    ctx = _base_context("")

    def pass_a(_prompt: str) -> str:
        return _pass_a_response([], confidence=0.9)

    def pass_b(_prompt: str) -> str:  # pragma: no cover - should not be called
        raise AssertionError("Pass B should not run when Pass A is unclear")

    score = score_artefact(ctx, pass_a_llm=pass_a, pass_b_llm=pass_b)

    assert score.status == "NEEDS_REVIEW"
    assert score.completion_estimate == 0


def test_unrelated_evidence_sets_completion_zero():
    ctx = _base_context("Annual leave form")

    def pass_a(_prompt: str) -> str:
        return _pass_a_response([{"claim": "Annual leave taken", "quantifier": 10, "timeframe": "2025"}])

    def pass_b(_prompt: str) -> str:
        return _pass_b_response([], completion=0.6, rating=4, tier="Transformational")

    score = score_artefact(ctx, pass_a_llm=pass_a, pass_b_llm=pass_b)

    assert score.completion_estimate == 0.0
    assert score.llm_recommended_rating == 2
    assert score.llm_recommended_tier == "Needs Review"


def test_system_tier_overrides_llm():
    ctx = _base_context("Short email note")

    def pass_a(_prompt: str) -> str:
        return _pass_a_response([{"claim": "Short email", "quantifier": None, "timeframe": None}])

    def pass_b(_prompt: str) -> str:
        return _pass_b_response(
            [{"kpa_code": "KPA1", "kpi_id": "T1", "match_strength": 0.4, "justification": "email"}],
            completion=0.2,
            rating=5,
            tier="Transformational",
            impact="LLM thinks transformational",
        )

    score = score_artefact(ctx, pass_a_llm=pass_a, pass_b_llm=pass_b)

    assert score.final_tier != score.llm_recommended_tier
    assert score.final_tier == "Needs Review"
    assert score.final_rating <= score.llm_recommended_rating
