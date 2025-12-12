from __future__ import annotations

import json
import textwrap
from dataclasses import replace
from typing import Any, Dict, Iterable, List, Sequence

from backend.llm.ollama_client import extract_json_object, query_ollama
from backend.staff_profile import KPA, KPI, StaffProfile, staff_is_director_level


def _normalise(text: str) -> str:
    return " ".join((text or "").lower().split())


def _skeleton_lookup(rows: Sequence[Sequence[Any]] | None) -> Dict[str, Dict[str, Any]]:
    lookup: Dict[str, Dict[str, Any]] = {}
    if not rows:
        return lookup
    for row in rows:
        if not row:
            continue
        name = _normalise(str(row[0] if len(row) > 0 else ""))
        if not name:
            continue
        lookup[name] = {
            "outcomes": str(row[5]).strip() if len(row) > 5 and row[5] is not None else "",
            "weight": row[3] if len(row) > 3 else None,
            "hours": row[4] if len(row) > 4 else None,
        }
    return lookup


def _contract_payload(profile: StaffProfile, skeleton_rows: Sequence[Sequence[Any]] | None) -> Dict[str, Any]:
    skeleton_map = _skeleton_lookup(skeleton_rows)
    payload: Dict[str, Any] = {
        "staff": {
            "id": profile.staff_id,
            "name": profile.name,
            "position": profile.position,
            "cycle_year": profile.cycle_year,
            "staff_level": "director" if staff_is_director_level(profile) else "academic",
        },
        "kpas": [],
    }

    for kpa in profile.kpas:
        key = _normalise(kpa.name)
        skeleton = skeleton_map.get(key, {})
        ta_context = kpa.ta_context or {}
        payload["kpas"].append(
            {
                "code": kpa.code,
                "name": kpa.name,
                "weight_pct": ta_context.get("weight_pct", kpa.weight),
                "hours": ta_context.get("hours", kpa.hours),
                "ta_context": ta_context,
                "skeleton_outcomes": skeleton.get("outcomes", ""),
                "existing_kpis": [kp.description for kp in kpa.kpis],
            }
        )
    return payload


def _build_prompt(profile: StaffProfile, skeleton_rows: Sequence[Sequence[Any]] | None) -> str:
    payload = _contract_payload(profile, skeleton_rows)
    payload_json = json.dumps(payload, ensure_ascii=False, indent=2)
    prompt = f"""
    You are enriching a Performance Agreement after the Task Agreement skeleton exists.
    Use the Task Agreement context and skeleton outcomes to propose measurable outputs, KPIs, and refined outcomes per KPA.

    Staff level: {payload['staff']['staff_level']} (keep hours and weight_pct exactly as provided; do not invent new allocations).

    Contract snapshot (JSON):
    {payload_json}

    Rules:
    - Use only the KPA codes provided. Do not add or remove KPAs.
    - Align outputs and outcomes directly to the TA context (modules, research, leadership, OHS, social responsiveness, etc.).
    - KPIs must be measurable with clear measure/target/due fields and relevant evidence_types.
    - Prefer concrete quantities or deadlines over generic "3" targets.
    - Mark generated content with generated_by_ai=true at both KPA and KPI levels.
    - Keep existing hours/weight_pct unchanged; you are not allowed to redistribute them.

    Respond ONLY with valid JSON in this shape:
    {{
      "kpas": [
        {{
          "code": "KPA1",
          "outputs": ["..."],
          "kpis": [{{"kpi": "...", "measure": "...", "target": "...", "due": "...", "evidence_types": ["..."], "generated_by_ai": true}}],
          "outcomes": ["..."],
          "generated_by_ai": true
        }}
      ]
    }}
    No narration before or after the JSON.
    """
    return textwrap.dedent(prompt).strip()


def _choose_block(kpa: KPA, plan: Dict[str, Any]) -> Dict[str, Any]:
    blocks: Iterable[Dict[str, Any]] = plan.get("kpas", []) or []
    for block in blocks:
        if _normalise(str(block.get("code", ""))) == _normalise(kpa.code):
            return block
        if _normalise(str(block.get("name", ""))) == _normalise(kpa.name):
            return block
    return {}


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _apply_plan(profile: StaffProfile, plan: Dict[str, Any], skeleton_rows: Sequence[Sequence[Any]] | None) -> List[KPA]:
    skeleton_map = _skeleton_lookup(skeleton_rows)
    updated_kpas: List[KPA] = []

    for kpa in profile.kpas:
        clone = replace(
            kpa,
            context=dict(kpa.context or {}),
            ta_context=dict(kpa.ta_context or {}),
            kpis=list(kpa.kpis or []),
        )
        block = _choose_block(kpa, plan)
        if not block:
            updated_kpas.append(clone)
            continue

        outputs = _as_list(block.get("outputs"))
        outcomes = _as_list(block.get("outcomes"))
        kpis_raw = block.get("kpis") or []

        bullet_outputs = "\n".join(f"• {o}" for o in outputs)
        bullet_outcomes = "\n".join(f"• {o}" for o in outcomes)

        kpi_count = max(1, len(kpis_raw))
        per_kpi_weight = float(clone.weight or 0.0) / kpi_count
        per_kpi_hours = float(clone.hours or 0.0) / kpi_count

        new_kpis: List[KPI] = []
        for raw in kpis_raw:
            measure = str(raw.get("measure", "")).strip()
            target = str(raw.get("target", "")).strip()
            due = str(raw.get("due", "")).strip()
            evidence_types = _as_list(raw.get("evidence_types"))

            description = str(raw.get("kpi") or raw.get("description") or "").strip()
            details = [f"Measure: {measure}" if measure else "", f"Target: {target}" if target else "", f"Due: {due}" if due else ""]
            evidence_note = "; ".join(evidence_types)
            if evidence_note:
                details.append(f"Evidence: {evidence_note}")
            suffix_bits = [d for d in details if d]
            if suffix_bits:
                suffix = "; ".join(suffix_bits)
                description = f"{description} ({suffix})" if description else suffix

            new_kpis.append(
                KPI(
                    description=description,
                    outputs=bullet_outputs,
                    outcomes=bullet_outcomes,
                    measure=measure,
                    target=target,
                    due=due,
                    evidence_types=evidence_types,
                    generated_by_ai=bool(raw.get("generated_by_ai", True)),
                    weight=per_kpi_weight,
                    hours=per_kpi_hours,
                    active=True,
                )
            )

        if new_kpis:
            clone.kpis = new_kpis
            clone.context["generated_by_ai"] = bool(block.get("generated_by_ai", True))
            clone.context["ai_outputs"] = outputs
            clone.context["ai_outcomes"] = outcomes or [skeleton_map.get(_normalise(kpa.name), {}).get("outcomes", "")]

        updated_kpas.append(clone)

    return updated_kpas


def enrich_pa_with_ai(profile: StaffProfile, skeleton_rows: Sequence[Sequence[Any]] | None) -> Dict[str, Any]:
    if not profile.kpas:
        raise ValueError("Profile contains no KPAs to enrich")

    prompt = _build_prompt(profile, skeleton_rows)
    raw = query_ollama(prompt, format="json")
    plan = extract_json_object(raw)
    if "kpas" not in plan:
        raise ValueError("AI response missing 'kpas' list")

    updated_kpas = _apply_plan(profile, plan, skeleton_rows)
    profile.kpas = updated_kpas
    profile.save()
    return plan
