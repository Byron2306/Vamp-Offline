import math

from backend.batch7_scorer import ArtefactScore, MatchedKPI
from backend.batch8_aggregator import FinalPerformance, KPASummary, aggregate_performance, export_final_summary_csv


class SimpleKPI:
    def __init__(self, kpi_id: str, evidence_types=None):
        self.kpi_id = kpi_id
        self.evidence_types = evidence_types or []


class SimpleKPA:
    def __init__(self, code: str, weight_pct: float, kpis, name: str | None = None):
        self.code = code
        self.name = name or code
        self.weight_pct = weight_pct
        self.kpis = kpis


class SimpleContract:
    def __init__(self, kpas):
        self.kpas = kpas


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------


def _artefact(
    *,
    filename: str,
    evidence_type: str,
    kpi_id: str,
    completion: float,
    cred: float = 1.0,
    confidence: float = 0.9,
) -> ArtefactScore:
    return ArtefactScore(
        filename=filename,
        evidence_type=evidence_type,
        matched_kpis=[MatchedKPI(kpa_code="", kpi_id=kpi_id, match_strength=0.9, justification="")],
        completion_estimate=completion,
        credibility_weight=cred,
        llm_recommended_rating=0,
        llm_recommended_tier="",
        final_rating=0,
        final_tier="",
        impact_summary="",
        confidence=confidence,
        status="SCORED",
        extract_status="ok",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_single_strong_artefact_completes_kpi():
    contract = SimpleContract([SimpleKPA("KPA1", 100.0, [SimpleKPI("KPI1", ["Exam"])], "Teaching")])
    artefacts = [
        _artefact(
            filename="exam1.docx",
            evidence_type="Exam",
            kpi_id="KPI1",
            completion=1.0,
            cred=0.9,
            confidence=0.9,
        )
    ]

    kpa_summaries, final_perf, kpi_results = aggregate_performance(contract, artefacts)

    assert math.isclose(kpi_results["KPI1"].completion, 0.81, rel_tol=1e-4)
    assert kpi_results["KPI1"].status == "ACHIEVED"
    assert kpa_summaries[0].status == "ACHIEVED"
    assert final_perf.final_rating == 4
    assert final_perf.final_tier == "Transformational"


def test_many_weak_artefacts_accumulate_to_partial():
    contract = SimpleContract([SimpleKPA("KPA1", 100.0, [SimpleKPI("KPI1", ["Report"])], "Research")])
    artefacts = [
        _artefact(filename=f"r{i}.pdf", evidence_type="Report", kpi_id="KPI1", completion=0.25)
        for i in range(3)
    ]

    kpa_summaries, final_perf, kpi_results = aggregate_performance(contract, artefacts)

    assert 0.65 < kpi_results["KPI1"].completion < 0.7
    assert kpi_results["KPI1"].status == "PARTIALLY ACHIEVED"
    assert kpa_summaries[0].status == "PARTIALLY ACHIEVED"
    assert final_perf.final_rating == 3


def test_low_credibility_screenshot_does_not_complete():
    contract = SimpleContract([SimpleKPA("KPA1", 100.0, [SimpleKPI("KPI1", ["Screenshot"])], "Teaching")])
    artefacts = [
        _artefact(
            filename="shot.png",
            evidence_type="Screenshot",
            kpi_id="KPI1",
            completion=1.0,
            cred=0.3,
            confidence=0.9,
        )
    ]

    kpa_summaries, final_perf, kpi_results = aggregate_performance(contract, artefacts)

    assert kpi_results["KPI1"].completion < 0.4
    assert kpi_results["KPI1"].status == "NOT ACHIEVED"
    assert final_perf.final_rating == 1


def test_missing_kpis_forces_review():
    contract = SimpleContract([SimpleKPA("KPA1", 100.0, [], "Leadership")])
    artefacts: list[ArtefactScore] = []

    kpa_summaries, final_perf, kpi_results = aggregate_performance(contract, artefacts)

    assert kpa_summaries[0].status == "NEEDS_REVIEW_MISSING_KPIS"
    assert kpa_summaries[0].kcr == 0.0
    assert final_perf.final_rating == 1
    assert all(result.completion == 0 for result in kpi_results.values())


def test_high_score_blocked_by_weak_kpa_for_tier():
    contract = SimpleContract(
        [
            SimpleKPA("KPA1", 95.0, [SimpleKPI("KPI1", ["Report"])], "Teaching"),
            SimpleKPA("KPA2", 5.0, [SimpleKPI("KPI2", ["Report"])], "Research"),
        ]
    )
    artefacts = [
        _artefact(filename="r1.pdf", evidence_type="Report", kpi_id="KPI1", completion=1.0),
        _artefact(filename="r2.pdf", evidence_type="Report", kpi_id="KPI2", completion=0.3),
    ]

    kpa_summaries, final_perf, _ = aggregate_performance(contract, artefacts)

    kpa_scores = {summary.kpa_code: summary.kcr for summary in kpa_summaries}
    assert kpa_scores["KPA1"] > 0.85
    assert kpa_scores["KPA2"] < 0.4
    assert final_perf.final_rating == 5
    assert final_perf.final_tier == "Compliance / Needs Improvement"


def test_csv_export_contains_overall_row(tmp_path):
    contract = SimpleContract([SimpleKPA("KPA1", 100.0, [SimpleKPI("KPI1", ["Report"])], "Teaching")])
    artefacts = [_artefact(filename="r1.pdf", evidence_type="Report", kpi_id="KPI1", completion=1.0)]

    kpa_summaries, final_perf, _ = aggregate_performance(contract, artefacts)
    out_path = export_final_summary_csv("12345", 2025, kpa_summaries, final_perf, output_dir=tmp_path)

    content = out_path.read_text(encoding="utf-8").splitlines()
    assert content[0].startswith("KPA,Weight %,Completion %,Status,Artefact Count")
    assert any(line.startswith("OVERALL,100") for line in content)
