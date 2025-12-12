from __future__ import annotations

"""
Batch 7 – LLM-assisted scoring orchestrator.

Implements the strict EXTRACT → CLASSIFY → UNDERSTAND → MAP → RECOMMEND → VALIDATE →
PERSIST flow described in the Batch 7 spec. The LLM is only used for the two
understanding/mapping passes; everything else is deterministic and auditable.
"""

import json
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional, Sequence

JsonCallable = Callable[[str], str]


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


def _clamp_confidence(value: float) -> float:
    if value < 0:
        return 0.0
    if value > 1:
        return 1.0
    return value


@dataclass
class Artefact:
    filename: str
    extension: str
    extracted_text: str
    extract_status: str
    extract_error: Optional[str] = None


@dataclass
class EvidenceClassification:
    evidence_type: str
    category: str
    credibility_weight: float


@dataclass
class KPIContract:
    kpi_id: str
    kpi: str
    measure: str
    target: str
    evidence_types: List[str]


@dataclass
class KPAContract:
    code: str
    name: str
    weight_pct: float
    kpis: List[KPIContract]


@dataclass
class ContractSummary:
    staff_no: str
    year: int
    post_level: str
    kpas: List[KPAContract] = field(default_factory=list)


@dataclass
class ScoringContext:
    artefact: Artefact
    evidence_classification: EvidenceClassification
    contract_summary: ContractSummary


@dataclass
class PassAResult:
    evidence_type: str
    claims: List[Dict[str, Any]]
    identified_modules: List[str]
    confidence: float


@dataclass
class MatchedKPI:
    kpa_code: str
    kpi_id: str
    match_strength: float
    justification: str


@dataclass
class PassBResult:
    matched_kpis: List[MatchedKPI]
    completion_estimate: float
    recommended_rating: int
    recommended_tier: str
    impact_summary: str
    confidence: float


@dataclass
class ArtefactScore:
    filename: str
    evidence_type: str
    matched_kpis: List[MatchedKPI]
    completion_estimate: float
    llm_recommended_rating: int
    llm_recommended_tier: str
    final_rating: int
    final_tier: str
    impact_summary: str
    confidence: float
    status: str
    extract_status: str
    kpa_codes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["matched_kpis"] = [asdict(m) for m in self.matched_kpis]
        data["kpa_codes"] = self.kpa_codes
        return data


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

PASS_A_PROMPT = (
    "You are analysing an artefact for a North-West University performance review.\n"
    "\n"
    "TASK:\n"
    "1. Identify what this artefact is.\n"
    "2. Extract factual claims only.\n"
    "3. Do NOT evaluate performance.\n"
    "4. Do NOT mention KPAs, ratings, or tiers.\n"
    "\n"
    "Return ONLY valid JSON matching this schema.\n"
    "{\n"
    '  "evidence_type": "string",\n'
    '  "claims": [\n'
    '    {\n'
    '      "claim": "string",\n'
    '      "quantifier": "number | null",\n'
    '      "timeframe": "string | null"\n'
    "    }\n"
    "  ],\n"
    '  "identified_modules": ["string"],\n'
    '  "confidence": 0.0\n'
    "}"
)

PASS_B_PROMPT_PREFIX = (
    "You are mapping evidence to a fixed performance contract.\n\n"
    "RULES:\n"
    "- You may ONLY map to KPIs provided.\n"
    "- If no KPI matches, say so explicitly.\n"
    "- Do NOT invent KPIs.\n"
    "- Estimate strength of alignment.\n"
    "\n"
    "Return ONLY valid JSON.\n"
)


def _truncate(text: str, limit: int = 1800) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


# ---------------------------------------------------------------------------
# JSON parsing helpers
# ---------------------------------------------------------------------------


def _parse_json_with_repair(raw: str) -> Dict[str, Any]:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            repaired = raw[start : end + 1]
            return json.loads(repaired)
        raise


# ---------------------------------------------------------------------------
# Deterministic helpers
# ---------------------------------------------------------------------------


def _deterministic_tier(completion: float) -> str:
    if completion >= 0.85:
        return "Transformational"
    if completion >= 0.6:
        return "Developmental"
    if completion >= 0.3:
        return "Compliance"
    return "Needs Review"


def _deterministic_rating(completion: float) -> int:
    if completion >= 0.85:
        return 5
    if completion >= 0.6:
        return 4
    if completion >= 0.3:
        return 3
    if completion > 0:
        return 2
    return 1


# ---------------------------------------------------------------------------
# Pass runners
# ---------------------------------------------------------------------------


def _run_pass_a(ctx: ScoringContext, llm_fn: JsonCallable) -> PassAResult:
    prompt = PASS_A_PROMPT
    prompt += f"\nFilename: {ctx.artefact.filename}\n"
    prompt += f"Evidence type: {ctx.evidence_classification.evidence_type}\n"
    prompt += f"Extracted text:\n{_truncate(ctx.artefact.extracted_text)}\n"

    raw = llm_fn(prompt)
    data = _parse_json_with_repair(raw)

    claims = data.get("claims") or []
    confidence = _clamp_confidence(float(data.get("confidence", 0)))

    return PassAResult(
        evidence_type=str(data.get("evidence_type") or ctx.evidence_classification.evidence_type),
        claims=claims,
        identified_modules=list(data.get("identified_modules") or []),
        confidence=confidence,
    )


def _run_pass_b(ctx: ScoringContext, pass_a: PassAResult, llm_fn: JsonCallable) -> PassBResult:
    kpi_lines: List[str] = []
    for kpa in ctx.contract_summary.kpas:
        for kpi in kpa.kpis:
            kpi_lines.append(
                f"- {kpa.code}:{kpi.kpi_id} — {kpi.kpi} | measure={kpi.measure} | target={kpi.target}"
            )

    prompt = PASS_B_PROMPT_PREFIX
    prompt += "Available KPIs:\n" + "\n".join(kpi_lines[:80]) + "\n\n"
    prompt += "PASS A OUTPUT:\n" + json.dumps(pass_a.__dict__, ensure_ascii=False) + "\n"

    raw = llm_fn(prompt)
    data = _parse_json_with_repair(raw)

    matched: List[MatchedKPI] = []
    for item in data.get("matched_kpis") or []:
        matched.append(
            MatchedKPI(
                kpa_code=str(item.get("kpa_code") or ""),
                kpi_id=str(item.get("kpi_id") or ""),
                match_strength=float(item.get("match_strength", 0)),
                justification=str(item.get("justification") or ""),
            )
        )

    completion = float(data.get("completion_estimate", 0))
    rating = int(data.get("recommended_rating", 1))
    tier = str(data.get("recommended_tier") or "Needs Review")
    impact = str(data.get("impact_summary") or "")
    confidence = _clamp_confidence(float(data.get("confidence", 0)))

    return PassBResult(
        matched_kpis=matched,
        completion_estimate=completion,
        recommended_rating=rating,
        recommended_tier=tier,
        impact_summary=impact,
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

CSV_COLUMNS: List[str] = [
    "filename",
    "evidence_type",
    "kpa_codes",
    "matched_kpis",
    "completion_estimate",
    "final_rating",
    "final_tier",
    "impact_summary",
    "confidence",
    "status",
    "extract_status",
]


def score_artefact(
    ctx: ScoringContext,
    *,
    pass_a_llm: JsonCallable,
    pass_b_llm: JsonCallable,
) -> ArtefactScore:
    contract_invalid = not ctx.contract_summary.kpas
    if contract_invalid:
        status = "NEEDS_REVIEW"
        return ArtefactScore(
            filename=ctx.artefact.filename,
            evidence_type=ctx.evidence_classification.evidence_type,
            matched_kpis=[],
            completion_estimate=0.0,
            llm_recommended_rating=2,
            llm_recommended_tier="Needs Review",
            final_rating=2,
            final_tier="Needs Review",
            impact_summary="Contract summary missing; manual review required.",
            confidence=0.0,
            status=status,
            extract_status=ctx.artefact.extract_status,
        )

    if ctx.artefact.extract_status != "ok":
        return ArtefactScore(
            filename=ctx.artefact.filename,
            evidence_type=ctx.evidence_classification.evidence_type,
            matched_kpis=[],
            completion_estimate=0.0,
            llm_recommended_rating=2,
            llm_recommended_tier="Needs Review",
            final_rating=2,
            final_tier="Needs Review",
            impact_summary=ctx.artefact.extract_error or "Extraction failed; manual review required.",
            confidence=0.0,
            status="NEEDS_REVIEW",
            extract_status=ctx.artefact.extract_status,
        )

    try:
        pass_a = _run_pass_a(ctx, pass_a_llm)
    except Exception:
        return ArtefactScore(
            filename=ctx.artefact.filename,
            evidence_type=ctx.evidence_classification.evidence_type,
            matched_kpis=[],
            completion_estimate=0.0,
            llm_recommended_rating=2,
            llm_recommended_tier="Needs Review",
            final_rating=2,
            final_tier="Needs Review",
            impact_summary="Automatic analysis failed; manual review required.",
            confidence=0.0,
            status="UNSCORABLE",
            extract_status=ctx.artefact.extract_status,
        )

    if not pass_a.claims or pass_a.confidence < 0.4:
        return ArtefactScore(
            filename=ctx.artefact.filename,
            evidence_type=pass_a.evidence_type,
            matched_kpis=[],
            completion_estimate=0.0,
            llm_recommended_rating=2,
            llm_recommended_tier="Needs Review",
            final_rating=2,
            final_tier="Needs Review",
            impact_summary="Evidence unclear; needs review.",
            confidence=pass_a.confidence,
            status="NEEDS_REVIEW",
            extract_status=ctx.artefact.extract_status,
        )

    try:
        pass_b = _run_pass_b(ctx, pass_a, pass_b_llm)
    except Exception:
        return ArtefactScore(
            filename=ctx.artefact.filename,
            evidence_type=pass_a.evidence_type,
            matched_kpis=[],
            completion_estimate=0.0,
            llm_recommended_rating=2,
            llm_recommended_tier="Needs Review",
            final_rating=2,
            final_tier="Needs Review",
            impact_summary="Automatic analysis failed; manual review required.",
            confidence=pass_a.confidence,
            status="UNSCORABLE",
            extract_status=ctx.artefact.extract_status,
        )

    matched_kpis = pass_b.matched_kpis
    completion_estimate = pass_b.completion_estimate
    recommended_rating = pass_b.recommended_rating
    recommended_tier = pass_b.recommended_tier or "Needs Review"
    impact_summary = pass_b.impact_summary

    if not matched_kpis:
        completion_estimate = 0.0
        recommended_rating = 2
        recommended_tier = "Needs Review"

    # Evidence-type credibility rule
    credibility_weight = ctx.evidence_classification.credibility_weight
    if credibility_weight < 0.5:
        completion_estimate = min(completion_estimate, 0.4)
        warning = " Low-credibility artefact; manual validation recommended."
        impact_summary = (impact_summary + warning).strip()
        # Flag low-credibility artefacts for review
        status_override = "NEEDS_REVIEW"
    else:
        status_override = None

    completion_estimate = max(0.0, min(1.0, completion_estimate))

    confidence = min(pass_a.confidence, pass_b.confidence)

    final_tier = _deterministic_tier(completion_estimate)
    final_rating = _deterministic_rating(completion_estimate)

    status = "SCORED"
    if ctx.artefact.extract_status != "ok":
        status = "NEEDS_REVIEW"
    elif confidence < 0.4:
        status = "NEEDS_REVIEW"
    elif status_override:
        status = status_override

    return ArtefactScore(
        filename=ctx.artefact.filename,
        evidence_type=pass_a.evidence_type,
        matched_kpis=matched_kpis,
        completion_estimate=completion_estimate,
        llm_recommended_rating=recommended_rating,
        llm_recommended_tier=recommended_tier,
        final_rating=final_rating,
        final_tier=final_tier,
        impact_summary=impact_summary,
        confidence=confidence,
        status=status,
        extract_status=ctx.artefact.extract_status,
        kpa_codes=sorted({m.kpa_code for m in matched_kpis if m.kpa_code}),
    )
