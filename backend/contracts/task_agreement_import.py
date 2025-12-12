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
from backend.staff_profile import DEFAULT_KPAS, KPA, StaffProfile


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

    return context


def import_task_agreement_excel(profile: StaffProfile, xlsx_path: Path) -> StaffProfile:
    """
    Parse an NWU / FEDU Task Agreement Excel file and attach the TA context
    to each KPA without converting rows into KPIs.

    The function modifies the profile in-place and then calls profile.save().
    """
    if not xlsx_path.exists():
        raise FileNotFoundError(f"Task Agreement Excel not found: {xlsx_path}")

    summary: Dict[str, Any] = parse_task_agreement(str(xlsx_path))
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
