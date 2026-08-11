from __future__ import annotations

import importlib
import os
import re
import sys
from pathlib import Path
from typing import Any

MIN_MATCH_STRENGTH = 0.50
MIN_REASONING_CONFIDENCE = 0.40


def _load_spine():
    candidates = []
    env_dir = str(os.getenv("DIO_EPISTEMIC_SPINE_DIR") or "").strip()
    if env_dir:
        candidates.append(Path(env_dir).expanduser())
    candidates.append(Path.home() / "DIO-Full-Audit" / "scripts")
    for candidate in candidates:
        if candidate.is_dir() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
    try:
        spine = importlib.import_module("dio_epistemic_spine")
    except Exception as exc:
        raise RuntimeError(
            "DIO epistemic spine unavailable; VAMP scoring authority is refused."
        ) from exc
    for name in ("claim_epistemic_state", "epistemic_tokens"):
        if not callable(getattr(spine, name, None)):
            raise RuntimeError(
                f"DIO epistemic spine missing required primitive: {name}"
            )
    return spine


def _value(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _contract_pairs(contract_summary: Any) -> set[tuple[str, str]]:
    pairs = set()
    for kpa in _value(contract_summary, "kpas", []) or []:
        kpa_code = str(_value(kpa, "code", "") or "").strip()
        for kpi in _value(kpa, "kpis", []) or []:
            kpi_id = str(_value(kpi, "kpi_id", "") or "").strip()
            if kpa_code and kpi_id:
                pairs.add((kpa_code, kpi_id))
    return pairs


def _ground_claims(extracted_text: str, claims: list[Any]) -> dict[str, Any]:
    spine = _load_spine()
    source = _norm(extracted_text)
    receipts = []
    grounded = 0
    for index, raw in enumerate(claims or []):
        exact_span = str(_value(raw, "exact_span", "") or "")
        span_norm = _norm(exact_span)
        present = bool(span_norm) and span_norm in source
        if present:
            grounded += 1
        receipts.append({
            "index": index,
            "claim": str(_value(raw, "claim", "") or ""),
            "exact_span": exact_span,
            "exact_span_present": present,
            "authority": "SOURCE_BOUND" if present else "UNVERIFIED",
        })

    state = spine.claim_epistemic_state(
        support_count=grounded,
        partial_support_count=max(0, len(receipts) - grounded) if grounded else 0,
    )
    all_grounded = bool(receipts) and grounded == len(receipts)
    return {
        "epistemic_state": state,
        "claims_seen": len(receipts),
        "grounded_claims": grounded,
        "claim_receipts": receipts,
        "passed": all_grounded,
        "all_claims_source_bound": all_grounded,
    }


def authorize_scoring_passes(
    ctx: Any,
    pass_a: Any,
    pass_b: Any,
    *,
    min_match_strength: float = MIN_MATCH_STRENGTH,
) -> dict[str, Any]:
    contract_pairs = _contract_pairs(_value(ctx, "contract_summary"))
    artefact = _value(ctx, "artefact")
    grounding = _ground_claims(
        str(_value(artefact, "extracted_text", "") or ""),
        list(_value(pass_a, "claims", []) or []),
    )

    authorized_pairs = []
    strengths = []
    match_receipts = []

    for raw in _value(pass_b, "matched_kpis", []) or []:
        kpa_code = str(_value(raw, "kpa_code", "") or "").strip()
        kpi_id = str(_value(raw, "kpi_id", "") or "").strip()
        try:
            strength = float(_value(raw, "match_strength", 0.0) or 0.0)
        except Exception:
            strength = 0.0
        strength = max(0.0, min(1.0, strength))
        known_pair = (kpa_code, kpi_id) in contract_pairs
        strong_enough = strength >= float(min_match_strength)
        authorized = known_pair and strong_enough
        if authorized:
            authorized_pairs.append((kpa_code, kpi_id))
            strengths.append(strength)
        match_receipts.append({
            "kpa_code": kpa_code,
            "kpi_id": kpi_id,
            "match_strength": strength,
            "known_contract_pair": known_pair,
            "strong_enough": strong_enough,
            "mapping_candidate": authorized,
            "authorized": False,
        })

    try:
        pass_a_conf = float(_value(pass_a, "confidence", 0.0) or 0.0)
    except Exception:
        pass_a_conf = 0.0
    try:
        pass_b_conf = float(_value(pass_b, "confidence", 0.0) or 0.0)
    except Exception:
        pass_b_conf = 0.0

    confidence_pass = (
        pass_a_conf >= MIN_REASONING_CONFIDENCE
        and pass_b_conf >= MIN_REASONING_CONFIDENCE
    )

    reasons = []
    if not grounding["passed"]:
        reasons.append("not_all_factual_claims_source_bound")
    if not authorized_pairs:
        reasons.append("no_authorized_contract_kpi_match")
    if not confidence_pass:
        reasons.append("reasoning_confidence_below_floor")

    mapping_candidates = list(authorized_pairs)

    # Mapping strength alone is never scoring authority. If any higher-order
    # epistemic gate fails, no pair may carry completion into scoring.
    passed = not reasons
    if not passed:
        authorized_pairs = []
        strengths = []

    authorized_set = set(authorized_pairs)
    for receipt in match_receipts:
        pair = (receipt["kpa_code"], receipt["kpi_id"])
        receipt["authorized"] = pair in authorized_set

    return {
        "schema": "dio.vamp.epistemic_authority.v1",
        "passed": passed,
        "release_status": (
            "AUTHORIZED_FOR_DETERMINISTIC_SCORING"
            if passed else "NEEDS_HUMAN_REVIEW"
        ),
        "reasons": reasons,
        "grounding": grounding,
        "match_receipts": match_receipts,
        "mapping_candidates": [list(pair) for pair in mapping_candidates],
        "authorized_pairs": [list(pair) for pair in authorized_pairs],
        "completion_cap": max(strengths) if strengths else 0.0,
        "confidence_pass": confidence_pass,
        "truth_determined_by_confidence": False,
    }


def authorized_pair_set(receipt: dict[str, Any]) -> set[tuple[str, str]]:
    return {
        (str(pair[0]), str(pair[1]))
        for pair in receipt.get("authorized_pairs", [])
        if isinstance(pair, (list, tuple)) and len(pair) == 2
    }
