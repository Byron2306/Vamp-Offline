# backend/nwu_brain_scorer.py
"""
Light-weight offline NWU brain scorer.

Uses the JSON packs in backend/data/nwu_brain to:
- Route evidence deterministically to a primary KPA (KPA1..KPA5)
- Infer a tier label (Transformational / Developmental / Compliance)
- Detect NWU core values from values_index.json
- Detect policy hits from policy_registry.json
- Combine these into a 0–5 rating using institution_profile.json

This is intentionally simpler than the full NWUScorer used in the online system,
but it respects your existing heuristic JSONs and keeps scoring deterministic.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Any, Tuple


BASE_DIR = Path(__file__).resolve().parent
BRAIN_DIR = BASE_DIR / "data" / "nwu_brain"


def _load_json(name: str) -> Any:
    path = BRAIN_DIR / name
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


# ---------- Data containers ----------

@dataclass
class BrainConfig:
    kpa_router: Dict[str, Any]
    values_index: Dict[str, Any]
    tier_keywords: Dict[str, List[str]]
    institution_profile: Dict[str, Any]
    policy_registry: Dict[str, Any]


_BRAIN: BrainConfig | None = None


def load_brain() -> BrainConfig:
    global _BRAIN
    if _BRAIN is None:
        _BRAIN = BrainConfig(
            kpa_router=_load_json("kpa_router.json"),
            values_index=_load_json("values_index.json"),
            tier_keywords=_load_json("tier_keywords.json"),
            institution_profile=_load_json("institution_profile.json"),
            policy_registry=_load_json("policy_registry.json"),
        )
    return _BRAIN


# ---------- KPA routing ----------

def _score_kpa_for_text(
    filename: str,
    extension: str,
    text: str,
    kpa_hint_code: str | None = None,
) -> Tuple[str, Dict[str, float]]:
    brain = load_brain()
    router = brain.kpa_router
    defaults = router.get("defaults", {})
    weights = defaults.get("score_weights", {})
    flags_str = defaults.get("regex_flags", "i,m")
    flags = 0
    if "i" in flags_str:
        flags |= re.IGNORECASE
    if "m" in flags_str:
        flags |= re.MULTILINE

    min_route_score = defaults.get("min_route_score", 1.5)
    fname = filename.lower()
    ext = extension.lower().lstrip(".")
    scores: Dict[str, float] = {}

    for kpa_code in ("KPA1", "KPA2", "KPA3", "KPA4", "KPA5"):
        cfg = router.get(kpa_code, {})
        score = 0.0

        # Extension cues
        extensions = cfg.get("extensions", [])
        if ext in extensions:
            score += float(weights.get("extension_cues", 0.5))

        # Filename cues
        for pat in cfg.get("filename_cues", []):
            try:
                if re.search(pat, fname, flags):
                    score += float(weights.get("filename_cues", 1.0))
            except re.error:
                continue

        # Content regex
        for pat in cfg.get("content_regex", []):
            try:
                if re.search(pat, text, flags):
                    score += float(weights.get("content_regex", 2.0))
            except re.error:
                continue

        # Negative cues
        for pat in cfg.get("negative_cues", []):
            try:
                if re.search(pat, text, flags) or re.search(pat, fname, flags):
                    score += float(weights.get("negative_cues", -2.5))
            except re.error:
                continue

        scores[kpa_code] = score

    # Choose best KPA
    best_kpa = max(scores, key=scores.get)
    best_score = scores.get(best_kpa, 0.0)

    # Respect explicit KPA hint if it's "close enough"
    if kpa_hint_code and kpa_hint_code in scores:
        hint_score = scores[kpa_hint_code]
        # If hint is not much worse than the best, prefer the hint
        if hint_score >= best_score - 0.2:
            best_kpa = kpa_hint_code
            best_score = hint_score

    # If everything is below threshold and we have a hint, fall back to hint
    if best_score < min_route_score and kpa_hint_code:
        best_kpa = kpa_hint_code

    return best_kpa, scores


# ---------- Values scoring ----------

def _score_values(text: str) -> Dict[str, Any]:
    brain = load_brain()
    core_values = brain.values_index.get("core_values", [])
    flags = re.IGNORECASE | re.MULTILINE

    hits: List[Dict[str, Any]] = []
    total_weight = 0.0

    for v in core_values:
        v_score = 0.0
        for kw in v.get("keywords", []):
            pattern = kw.get("pattern")
            weight = float(kw.get("weight", 1.0))
            if not pattern:
                continue
            try:
                if re.search(pattern, text, flags):
                    v_score += weight
            except re.error:
                continue

        if v_score > 0:
            hits.append(
                {
                    "id": v.get("id"),
                    "name": v.get("name"),
                    "score": v_score,
                }
            )
            total_weight += v_score

    hits.sort(key=lambda x: x["score"], reverse=True)

    # Very simple normalisation: assume 10+ is "maxed out"
    norm_score = min(1.0, total_weight / 10.0) if total_weight > 0 else 0.0

    return {
        "score": norm_score,
        "hits": hits,
    }


# ---------- Tier scoring ----------

def _score_tier(text: str) -> Tuple[str, Dict[str, int]]:
    brain = load_brain()
    tiers = brain.tier_keywords
    flags = re.IGNORECASE | re.MULTILINE

    scores: Dict[str, int] = {}
    for tier_name, phrases in tiers.items():
        count = 0
        for phrase in phrases:
            try:
                if re.search(phrase, text, flags):
                    count += 1
            except re.error:
                continue
        scores[tier_name] = count

    # Default if nothing matched
    if not scores:
        return "Developmental", {}

    best_tier = max(scores, key=scores.get)
    if scores[best_tier] == 0:
        best_tier = "Developmental"

    return best_tier, scores


# ---------- Policy scoring ----------

def _score_policies(text: str) -> Dict[str, Any]:
    brain = load_brain()
    registry = brain.policy_registry
    flags = re.IGNORECASE | re.MULTILINE

    hits: List[Dict[str, Any]] = []

    for code, cfg in registry.items():
        title = cfg.get("title", "")
        aliases = cfg.get("aliases", [])
        matched = False

        # Match on title
        if title:
            try:
                if re.search(re.escape(title), text, flags):
                    matched = True
            except re.error:
                pass

        # Match on aliases (e.g. ETHICS_POLICY etc.)
        if not matched:
            for alias in aliases:
                alias_text = alias.replace("_", " ")
                try:
                    if re.search(re.escape(alias_text), text, flags):
                        matched = True
                        break
                except re.error:
                    continue

        if matched:
            hits.append(
                {
                    "id": cfg.get("id") or cfg.get("code") or code,
                    "code": code,
                    "title": title,
                    "must_pass": bool(cfg.get("must_pass", False)),
                    "severity": cfg.get("severity", "med"),
                }
            )

    return {
        "hits": hits,
    }


# ---------- Rating / band aggregation ----------

def _aggregate_score(tier_label: str, values_score: float, policy_hits: Dict[str, Any]) -> Tuple[float, str]:
    brain = load_brain()
    inst = brain.institution_profile
    weights = inst.get("weights", {})

    # Tier → 0..1
    tier_map = {
        "Transformational": 1.0,
        "Developmental": 0.7,
        "Compliance": 0.4,
    }
    tier_component = tier_map.get(tier_label, 0.6)

    # Policy component: more hits → higher, with simple cap
    hits = policy_hits.get("hits", [])
    n_hits = len(hits)
    policy_component = min(1.0, n_hits / 3.0) if n_hits > 0 else 0.0

    # Values component: already 0..1
    values_component = values_score

    # KPA coverage: for a single artefact we treat as fully contributing
    kpa_coverage = 1.0

    tier_w = float(weights.get("tier", 0.4))
    pol_w = float(weights.get("policy", 0.3))
    val_w = float(weights.get("values", 0.2))
    kpa_w = float(weights.get("kpa_coverage", 0.1))

    composite_0_to_1 = (
        tier_component * tier_w
        + policy_component * pol_w
        + values_component * val_w
        + kpa_coverage * kpa_w
    )

    # Map 0..1 → 0..5 scale then into institutional bands
    rating_raw = composite_0_to_1 * 5.0

    bands = inst.get("rating_scale", {}).get("bands", [])
    band_label = "Unrated"
    for band in bands:
        if band["min"] <= rating_raw <= band["max"]:
            band_label = band.get("label", band_label)
            break

    return rating_raw, band_label


# ---------- Public API ----------

def brain_score_evidence(
    *,
    path: Path,
    full_text: str,
    kpa_hint_code: str | None = None,
) -> Dict[str, Any]:
    """
    Compute deterministic NWU scoring for a single evidence artefact.

    Returns a dict that can be merged into the existing ctx used by the GUI.
    """
    inst = load_brain().institution_profile
    kpas = inst.get("kpas", {})

    filename = path.name
    ext = path.suffix

    # KPA routing
    primary_kpa_code, kpa_scores = _score_kpa_for_text(
        filename=filename,
        extension=ext,
        text=full_text,
        kpa_hint_code=kpa_hint_code,
    )
    primary_kpa_name = kpas.get(primary_kpa_code, primary_kpa_code)

    # Values
    values = _score_values(full_text)

    # Tier
    tier_label, tier_scores = _score_tier(full_text)

    # Policies
    policies = _score_policies(full_text)

    # Aggregate
    rating_raw, rating_label = _aggregate_score(
        tier_label=tier_label,
        values_score=values["score"],
        policy_hits=policies,
    )

    return {
        "primary_kpa_code": primary_kpa_code,
        "primary_kpa_name": primary_kpa_name,
        "tier_label": tier_label,
        "rating": round(rating_raw, 1),
        "rating_label": rating_label,
        "values_hits": [v["name"] for v in values["hits"]],
        "values_detail": values,
        "policy_hits": policies.get("hits", []),
        "kpa_route_scores": kpa_scores,
        "tier_scores": tier_scores,
    }
