from __future__ import annotations

"""
Task Agreement importer for the offline VAMP app.

This version is deliberately aligned with backend.staff_profile so that the
Tkinter GUI, PA Excel generator and this importer all share the SAME
StaffProfile / KPA / KPI structures and JSON files.

Usage from the GUI:

    from backend.contracts.task_agreement_import import import_task_agreement_excel
    import_task_agreement_excel(self.staff_profile, Path(path))

The importer no longer converts TA rows into KPIs. Instead, it attaches the
parsed Task Agreement context (hours, teaching modules, supervision notes,
etc.) to the relevant KPA.ta_context fields and records a contract-level flag
so downstream tools can differentiate TA-sourced data from KPIs captured
elsewhere.
"""

from pathlib import Path
from typing import Any, Dict, List

from backend.expectation_engine import parse_task_agreement
from backend.staff_profile import DEFAULT_KPAS, KPA, StaffProfile, staff_is_director_level


def _ensure_kpa_map(profile: StaffProfile) -> Dict[str, KPA]:
    """
    Ensure the profile has the 5 canonical KPAs and return a code→KPA mapping.
    """
    kpas_by_code: Dict[str, KPA] = {k.code: k for k in profile.kpas}

    for code, name in DEFAULT_KPAS:
        if code not in kpas_by_code:
            kpas_by_code[code] = KPA(code=code, name=name, weight=None, hours=None, kpis=[])

    # Keep profile.kpas in canonical order
    profile.kpas = [kpas_by_code[code] for code, _ in DEFAULT_KPAS]
    return kpas_by_code


def _build_ta_context(kpa_code: str, summary: Dict[str, Any]) -> Dict[str, Any]:
    """
    Construct a TA context payload for a given KPA from the parsed summary.
    """

    context: Dict[str, Any] = {}
    kpa_summary = summary.get("kpa_summary", {}) or {}
    if kpa_code in kpa_summary:
        summary_block = kpa_summary[kpa_code]
        if isinstance(summary_block, dict):
            context.update(summary_block)

    norm_hours = summary.get("norm_hours")
    if norm_hours:
        context.setdefault("norm_hours", norm_hours)

    category_map: Dict[str, List[str]] = {
        "KPA1": ["teaching", "supervision", "teaching_practice_windows"],
        "KPA2": ["ohs"],
        "KPA3": ["research"],
        "KPA4": ["leadership"],
        "KPA5": ["social"],
    }

    for key in category_map.get(kpa_code, []):
        value = summary.get(key)
        if value:
            context[key] = value

    if kpa_code == "KPA4":
        people_management = summary.get("people_management")
        if people_management:
            context["people_management_items"] = list(people_management)

    return context


def _fold_people_management_summary(summary: Dict[str, Any], director_level: bool) -> Dict[str, Any]:
    """Merge TA People Management data into KPA4 for non-director staff."""

    if director_level:
        return summary

    merged_summary = dict(summary or {})
    kpa_summary = dict(merged_summary.get("kpa_summary") or {})
    people_management = list(merged_summary.get("people_management") or [])

    pm_block = kpa_summary.pop("KPA6", None)
    if pm_block:
        kpa4 = dict(kpa_summary.get("KPA4") or {})
        kpa4_hours = float(kpa4.get("hours", 0.0) or 0.0) + float(pm_block.get("hours", 0.0) or 0.0)
        kpa4_weight = float(kpa4.get("weight_pct", 0.0) or 0.0) + float(pm_block.get("weight_pct", 0.0) or 0.0)

        if not kpa4.get("name"):
            kpa4["name"] = pm_block.get("name", "Academic Leadership and Management")

        kpa4["hours"] = kpa4_hours
        kpa4["weight_pct"] = kpa4_weight
        kpa_summary["KPA4"] = kpa4

    merged_summary["kpa_summary"] = kpa_summary
    if people_management:
        merged_summary["people_management"] = people_management
    return merged_summary


def import_task_agreement_excel(profile: StaffProfile, xlsx_path: Path) -> StaffProfile:
    """
    Parse an NWU / FEDU Task Agreement Excel file and attach the TA context
    to each KPA without converting rows into KPIs.

    The function modifies the profile in-place and then calls profile.save().
    """
    if not xlsx_path.exists():
        raise FileNotFoundError(f"Task Agreement Excel not found: {xlsx_path}")

    director_level = staff_is_director_level(profile)
    summary: Dict[str, Any] = parse_task_agreement(
        str(xlsx_path), director_level=director_level
    )
    summary = _fold_people_management_summary(summary, director_level)
    kpa_map = _ensure_kpa_map(profile)

    for code, kpa_obj in kpa_map.items():
        existing_context = kpa_obj.ta_context or {}
        merged_context = dict(existing_context)
        new_context = _build_ta_context(code, summary)
        if new_context:
            merged_context.update(new_context)
        kpa_obj.ta_context = merged_context

    if "TA_IMPORTED" not in profile.flags:
        profile.flags.append("TA_IMPORTED")

    # Persist contract JSON via StaffProfile.save()
    profile.save()
    return profile
