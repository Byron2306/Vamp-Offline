from __future__ import annotations

"""Batch 8 – Deterministic aggregation and final scoring.

This module consumes Batch 7 artefact scores and a canonical performance
contract to produce NWU-aligned KPI/KPA completion scores, final ratings, tiers
and justification text. All logic is deterministic and audit-friendly, with no
LLM involvement.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from backend.batch7_scorer import ArtefactScore


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass
class NormalisedKPI:
    kpi_id: str
    evidence_types: List[str]


@dataclass
class NormalisedKPA:
    code: str
    name: str
    weight_pct: float
    kpis: List[NormalisedKPI]


@dataclass
class KPASummary:
    kpa_code: str
    kpa_name: str
    weight_pct: float
    kcr: float
    status: str
    contributing_artefacts: int


@dataclass
class FinalPerformance:
    overall_score: float
    final_rating: int
    final_tier: str
    justification: str


@dataclass
class KPIResult:
    kpi_id: str
    kpa_code: str
    completion: float
    status: str
    contributing_artefacts: int


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_RATING_BANDS: List[Dict[str, object]] = [
    {"min": 0.85, "max": 1.0, "rating": 5, "label": "Outstanding"},
    {"min": 0.70, "max": 0.84, "rating": 4, "label": "Exceeds Expectations"},
    {"min": 0.55, "max": 0.69, "rating": 3, "label": "Meets Expectations"},
    {"min": 0.40, "max": 0.54, "rating": 2, "label": "Partially Meets"},
    {"min": 0.0, "max": 0.39, "rating": 1, "label": "Does Not Meet"},
]

DEFAULT_TIER_RULES = {
    "transformational": {"min_rating": 4, "min_kpa": 0.6, "label": "Transformational"},
    "developmental": {"rating": 3, "min_kpa": 0.5, "label": "Developmental"},
    "needs_improvement": {"threshold": 0.4, "label": "Compliance / Needs Improvement"},
}

DEFAULT_CONFIDENCE_THRESHOLDS = {
    "evidence_min_confidence": 0.5,
    "credibility_min": 0.7,
}


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------


def _extract_value(obj: object, *names: str, default: object = "") -> object:
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
        if isinstance(obj, dict) and name in obj:
            return obj[name]
    return default


def _normalise_kpi(raw: object) -> Optional[NormalisedKPI]:
    kpi_id = _extract_value(raw, "kpi_id", "id", "kpi", default=None)
    if kpi_id is None:
        return None
    evidence = _extract_value(raw, "evidence_types", default=[]) or []
    evidence_types = [str(e) for e in evidence]
    return NormalisedKPI(kpi_id=str(kpi_id), evidence_types=evidence_types)


def _normalise_kpa(raw: object) -> Optional[NormalisedKPA]:
    code = _extract_value(raw, "code", default=None)
    name = _extract_value(raw, "name", default="")
    if code is None:
        return None
    weight = float(_extract_value(raw, "weight_pct", "weight", default=0.0) or 0.0)
    raw_kpis = _extract_value(raw, "kpis", default=[]) or []
    kpis: List[NormalisedKPI] = []
    for item in raw_kpis:
        normalised = _normalise_kpi(item)
        if normalised:
            kpis.append(normalised)
    return NormalisedKPA(code=str(code), name=str(name), weight_pct=weight, kpis=kpis)


def normalise_contract(contract: object) -> List[NormalisedKPA]:
    raw_kpas = _extract_value(contract, "kpas", default=[])
    if isinstance(raw_kpas, dict):
        raw_items: Iterable = raw_kpas.values()
    else:
        raw_items = raw_kpas or []

    kpas: List[NormalisedKPA] = []
    for raw in raw_items:
        normalised = _normalise_kpa(raw)
        if normalised:
            kpas.append(normalised)
    return kpas


# ---------------------------------------------------------------------------
# Core calculations
# ---------------------------------------------------------------------------


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    if value < low:
        return low
    if value > high:
        return high
    return value


def _compute_acs(score: ArtefactScore) -> float:
    if score.status != "SCORED":
        return 0.0
    base = score.completion_estimate * score.credibility_weight * score.confidence
    base = _clamp(base)
    if score.credibility_weight < 0.5:
        return min(base, 0.4)
    return base


def _kpi_status(kcs: float) -> str:
    if kcs >= 0.8:
        return "ACHIEVED"
    if kcs >= 0.5:
        return "PARTIALLY ACHIEVED"
    return "NOT ACHIEVED"


def _kpa_status(kcr: float, missing_kpis: bool, insufficient: bool) -> str:
    if missing_kpis:
        return "NEEDS_REVIEW_MISSING_KPIS"
    if insufficient:
        return "INSUFFICIENT_EVIDENCE"
    return _kpi_status(kcr)


def _deterministic_rating(ocs: float, rating_bands: List[Dict[str, object]]) -> Tuple[int, str]:
    for band in sorted(rating_bands, key=lambda b: float(b.get("min", 0)), reverse=True):
        minimum = float(band.get("min", 0))
        maximum = float(band.get("max", 1))
        if minimum <= ocs <= maximum:
            return int(band.get("rating", 1)), str(band.get("label", ""))
    return 1, ""


def _deterministic_tier(rating: int, kpa_scores: Dict[str, float], tier_rules: Dict[str, Dict[str, object]]) -> str:
    min_kpa = min(kpa_scores.values()) if kpa_scores else 0.0
    if rating >= tier_rules["transformational"].get("min_rating", 5) and min_kpa >= tier_rules[
        "transformational"
    ].get("min_kpa", 0.6):
        return str(tier_rules["transformational"].get("label", "Transformational"))
    if rating == tier_rules["developmental"].get("rating", 3) and min_kpa >= tier_rules["developmental"].get(
        "min_kpa", 0.5
    ):
        return str(tier_rules["developmental"].get("label", "Developmental"))
    if min_kpa < tier_rules["needs_improvement"].get("threshold", 0.4):
        return str(tier_rules["needs_improvement"].get("label", "Compliance / Needs Improvement"))
    return str(tier_rules["developmental"].get("label", "Developmental"))


def _justification_text(rating: int, rating_label: str, tier: str, kpa_summaries: Sequence[KPASummary]) -> str:
    kpa_clauses: List[str] = []
    for summary in kpa_summaries:
        status = summary.status.replace("_", " ")
        clause = (
            f"{summary.kpa_name} ({summary.weight_pct:.0f}% weighting) "
            f"is {status.lower()} with completion {summary.kcr:.2f}."
        )
        kpa_clauses.append(clause)
    kpa_sentence = " ".join(kpa_clauses) if kpa_clauses else "No KPA evidence available."
    return (
        f"The staff member achieved an overall performance rating of {rating} ({rating_label}). "
        f"Final tier: {tier}. {kpa_sentence}"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def aggregate_performance(
    contract: object,
    artefact_scores: Sequence[ArtefactScore],
    scoring_config: Optional[Dict[str, object]] = None,
) -> Tuple[List[KPASummary], FinalPerformance, Dict[str, KPIResult]]:
    config = scoring_config or {}
    rating_bands = list(config.get("rating_bands", DEFAULT_RATING_BANDS))
    tier_rules = dict(DEFAULT_TIER_RULES)
    tier_rules.update(config.get("tier_rules", {}))
    confidence_thresholds = dict(DEFAULT_CONFIDENCE_THRESHOLDS)
    confidence_thresholds.update(config.get("confidence_thresholds", {}))

    kpas = normalise_contract(contract)
    kpi_lookup: Dict[str, Tuple[str, List[str]]] = {}
    for kpa in kpas:
        for kpi in kpa.kpis:
            kpi_lookup[kpi.kpi_id] = (kpa.code, kpi.evidence_types)

    kpi_results: Dict[str, KPIResult] = {}
    kpa_contribution_files: Dict[str, set] = {kpa.code: set() for kpa in kpas}
    kpa_confidences: Dict[str, List[float]] = {kpa.code: [] for kpa in kpas}
    kpa_credibility: Dict[str, List[float]] = {kpa.code: [] for kpa in kpas}

    for score in artefact_scores:
        if score.status == "UNSCORABLE" or score.extract_status == "failed":
            continue
        acs = _compute_acs(score)
        for matched in score.matched_kpis:
            mapping = kpi_lookup.get(matched.kpi_id)
            if mapping is None:
                continue
            kpa_code, permitted_evidence = mapping
            if permitted_evidence and score.evidence_type not in permitted_evidence:
                continue
            if acs <= 0:
                continue
            result = kpi_results.get(matched.kpi_id)
            if result is None:
                result = KPIResult(
                    kpi_id=matched.kpi_id,
                    kpa_code=kpa_code,
                    completion=0.0,
                    status="NOT ACHIEVED",
                    contributing_artefacts=0,
                )
            result.completion += acs
            result.contributing_artefacts += 1
            kpi_results[matched.kpi_id] = result
            kpa_contribution_files[kpa_code].add(score.filename)
            kpa_confidences[kpa_code].append(score.confidence)
            kpa_credibility[kpa_code].append(score.credibility_weight)

    # Finalise KPI scores
    for kpi_id, result in kpi_results.items():
        result.completion = _clamp(result.completion)
        result.status = _kpi_status(result.completion)

    # Ensure KPIs with no evidence are still represented
    for kpa in kpas:
        for kpi in kpa.kpis:
            if kpi.kpi_id not in kpi_results:
                kpi_results[kpi.kpi_id] = KPIResult(
                    kpi_id=kpi.kpi_id,
                    kpa_code=kpa.code,
                    completion=0.0,
                    status="NOT ACHIEVED",
                    contributing_artefacts=0,
                )

    kpa_summaries: List[KPASummary] = []
    kpa_scores_for_tier: Dict[str, float] = {}
    for kpa in kpas:
        kpi_scores = [kpi_results[kpi.kpi_id].completion for kpi in kpa.kpis]
        missing_kpis = not kpa.kpis
        if missing_kpis:
            kcr = 0.0
        else:
            kcr = sum(kpi_scores) / len(kpi_scores) if kpi_scores else 0.0

        # Evidence sufficiency check
        insufficient = False
        if not missing_kpis:
            has_confident = any(c >= confidence_thresholds["evidence_min_confidence"] for c in kpa_confidences[kpa.code])
            has_credible = any(c >= confidence_thresholds["credibility_min"] for c in kpa_credibility[kpa.code])
            if not (has_confident and has_credible):
                insufficient = True
                kcr = min(kcr, 0.49)

        status = _kpa_status(kcr, missing_kpis=missing_kpis, insufficient=insufficient)
        kpa_summaries.append(
            KPASummary(
                kpa_code=kpa.code,
                kpa_name=kpa.name,
                weight_pct=kpa.weight_pct,
                kcr=kcr,
                status=status,
                contributing_artefacts=len(kpa_contribution_files[kpa.code]),
            )
        )
        kpa_scores_for_tier[kpa.code] = kcr

    weighted_scores = [summary.kcr * (summary.weight_pct / 100.0) for summary in kpa_summaries]
    overall_completion = _clamp(sum(weighted_scores))
    final_rating, rating_label = _deterministic_rating(overall_completion, rating_bands)
    final_tier = _deterministic_tier(final_rating, kpa_scores_for_tier, tier_rules)
    justification = _justification_text(final_rating, rating_label, final_tier, kpa_summaries)

    final = FinalPerformance(
        overall_score=overall_completion,
        final_rating=final_rating,
        final_tier=final_tier,
        justification=justification,
    )
    return kpa_summaries, final, kpi_results


def export_final_summary_csv(
    staff_id: str,
    year: str | int,
    kpa_summaries: Sequence[KPASummary],
    final_performance: FinalPerformance,
    output_dir: Optional[Path] = None,
) -> Path:
    output_dir = output_dir or Path(__file__).resolve().parents[1] / "offline_results"
    output_dir.mkdir(parents=True, exist_ok=True)

    filename = f"final_summary_{staff_id}_{year}.csv"
    out_path = output_dir / filename

    lines: List[str] = []
    header = ["KPA", "Weight %", "Completion %", "Status", "Artefact Count"]
    lines.append(",".join(header))
    for summary in kpa_summaries:
        lines.append(
            ",".join(
                [
                    summary.kpa_code,
                    f"{summary.weight_pct:.2f}",
                    f"{summary.kcr * 100:.2f}",
                    summary.status,
                    str(summary.contributing_artefacts),
                ]
            )
        )
    lines.append(
        ",".join(
            [
                "OVERALL",
                "100",
                f"{final_performance.overall_score * 100:.2f}",
                final_performance.final_tier,
                "-",
            ]
        )
    )

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path
