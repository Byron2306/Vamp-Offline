from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Sequence

from backend.staff_profile import KPI, KPA, StaffProfile

BASE_DIR = Path(__file__).resolve().parents[1]  # backend/
DATA_DIR = BASE_DIR / "data"

KPI_TAXONOMY_PATH = DATA_DIR / "kpi_taxonomy_nwu_education.json"
VALUES_PATH = DATA_DIR / "nwu_values_vocabulary.json"

OHS_CODE = "KPA5"
OHS_WEIGHT_PCT = 2.0
OHS_KPI_TEXT = "Compliance with institutional Occupational Health and Safety requirements"

MODULE_CODE_RE = re.compile(r"\b[A-Z]{3,}[0-9]{2,}\b")

def _load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _sanitise_outputs(text: str) -> str:
    # Remove obvious module codes to avoid accidental inclusion in KPI/Output fields.
    text = MODULE_CODE_RE.sub("", text or "")
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text

def _pick_kpi_count(hours: float | None) -> int:
    h = float(hours or 0.0)
    if h >= 80:
        return 4
    if h >= 40:
        return 3
    return 2

def _flatten_kpis(kpa_code: str, taxonomy: dict) -> List[str]:
    block = taxonomy.get(kpa_code) or {}
    items: List[str] = []
    if isinstance(block, dict):
        for _, arr in block.items():
            if isinstance(arr, list):
                items.extend([str(x).strip() for x in arr if str(x).strip()])
    elif isinstance(block, list):
        items.extend([str(x).strip() for x in block if str(x).strip()])
    # de-dup while preserving order
    seen=set()
    out=[]
    for x in items:
        if x not in seen:
            out.append(x); seen.add(x)
    return out

def _lock_ohs(profile: StaffProfile) -> StaffProfile:
    # Enforce OHS weight at contract level (2%) and strip modules/teaching leakage.
    kpas: List[KPA] = []
    for k in profile.kpas or []:
        if k.code == OHS_CODE:
            kpas.append(replace(
                k,
                weight=OHS_WEIGHT_PCT,
                kpis=[KPI(description=OHS_KPI_TEXT, outcomes="; ".join(_load_json(VALUES_PATH).keys()), generated_by_ai=False, weight=OHS_WEIGHT_PCT)]
            ))
        else:
            kpas.append(k)
    # ensure OHS exists
    if not any(k.code == OHS_CODE for k in kpas):
        kpas.append(KPA(code=OHS_CODE, name="Occupational Health and Safety", weight=OHS_WEIGHT_PCT,
                        kpis=[KPI(description=OHS_KPI_TEXT, outcomes="; ".join(_load_json(VALUES_PATH).keys()), generated_by_ai=False, weight=OHS_WEIGHT_PCT)]))
    profile.kpas = kpas
    return profile

def _renormalise_weights(profile: StaffProfile) -> None:
    # After locking OHS=2, scale others to sum 98 based on their current weights (or TA weights).
    other = [k for k in profile.kpas if k.code != OHS_CODE]
    total = sum(float(k.weight or 0.0) for k in other)
    if total <= 0:
        # fallback equal split across non-OHS KPAs present
        n = max(1, len(other))
        for k in other:
            k.weight = round(98.0 / n, 2)
    else:
        for k in other:
            k.weight = round((float(k.weight or 0.0) / total) * 98.0, 2)

def enrich_pa_from_libraries(profile: StaffProfile, skeleton_rows: Sequence[Sequence[Any]] | None) -> Dict[str, Any]:
    """Deterministically populate the profile's KPIs/outcomes from controlled libraries.

    - NO AI generation of KPI text or Outcomes.
    - OHS (KPA5) is fixed, singular KPI, and ALWAYS weighs 2%.
    - Other KPA weights are renormalised to sum to 98%.
    """
    if not profile.kpas:
        raise ValueError("Profile contains no KPAs to enrich")

    taxonomy = _load_json(KPI_TAXONOMY_PATH)
    values = _load_json(VALUES_PATH)
    value_outcomes = "; ".join(list(values.keys())) if isinstance(values, dict) else "; ".join(map(str, values))

    # lock OHS first
    _lock_ohs(profile)

    updated: List[KPA] = []
    for kpa in profile.kpas:
        if kpa.code == OHS_CODE:
            # already locked; ensure no module codes leak into outputs/outcomes
            locked_kpis=[KPI(description=OHS_KPI_TEXT, outcomes=value_outcomes, outputs="", generated_by_ai=False, weight=OHS_WEIGHT_PCT)]
            updated.append(replace(kpa, weight=OHS_WEIGHT_PCT, kpis=locked_kpis))
            continue

        choices = _flatten_kpis(kpa.code, taxonomy)
        n = _pick_kpi_count(getattr(kpa, "hours", None) or (kpa.ta_context or {}).get("hours"))
        n = min(max(2, n), max(2, len(choices))) if choices else 2
        picked = choices[:n] if choices else ["KPI to be selected from taxonomy"]

        # derive outputs from TA context, but sanitise module codes
        ta = kpa.ta_context or {}
        outputs = ""
        if isinstance(ta, dict):
            # prefer summary text if present
            outputs = str(ta.get("kpa_summary") or ta.get("summary") or "").strip()
        outputs = _sanitise_outputs(outputs)

        # allocate weight within KPA evenly across selected KPI rows
        kpa_weight = float(kpa.weight or 0.0)
        each_w = round(kpa_weight / max(1, len(picked)), 2) if kpa_weight else None

        kpis=[KPI(description=desc, outputs=outputs, outcomes=value_outcomes, generated_by_ai=False, weight=each_w) for desc in picked]
        updated.append(replace(kpa, kpis=kpis))

    profile.kpas = updated
    _renormalise_weights(profile)
    profile.save()

    return {
        "mode": "libraries",
        "ohs_fixed_weight_pct": OHS_WEIGHT_PCT,
        "kpa_count": len(profile.kpas),
        "values": list(values.keys()) if isinstance(values, dict) else values,
    }
