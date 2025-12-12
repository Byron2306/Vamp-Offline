from __future__ import annotations

"""Validation helpers for Task Agreement contracts.

This module exposes a single entry-point ``validate_ta_contract`` that performs
lightweight sanity checks on the parsed TA structure. It is intentionally
heuristic and avoids any I/O so that the GUI can cheaply gate actions (e.g.
generating PA skeletons or exporting artefacts) on clearly explained problems.
"""

from typing import Iterable, List, Tuple
import re


MONTH_TOKENS = {
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
    "jan",
    "feb",
    "mar",
    "apr",
    "jun",
    "jul",
    "aug",
    "sep",
    "sept",
    "oct",
    "nov",
    "dec",
}

NAME_PLACEHOLDER_RE = re.compile(r"\b(name|surname|first name|last name)\b", re.IGNORECASE)
NAME_LIKE_RE = re.compile(r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b")


def _as_text(value: object) -> str:
    if hasattr(value, "description"):
        return str(getattr(value, "description"))
    if isinstance(value, dict) and "description" in value:
        return str(value.get("description", ""))
    return str(value or "")


def _safe_float(value: object) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _iter_kpi_text(kpi_list: Iterable[object] | None) -> Iterable[str]:
    for item in kpi_list or []:
        text = _as_text(item).strip()
        if text:
            yield text


def validate_ta_contract(contract, director_level: bool | None = None) -> Tuple[bool, List[str], List[str]]:
    """Validate a parsed Task Agreement.

    Returns (is_valid, errors, warnings).  The function is intentionally
    defensive: failures surface as human-friendly messages instead of
    exceptions so that the GUI can display them directly.
    """

    errors: List[str] = []
    warnings: List[str] = []

    if contract is None:
        return False, ["No Task Agreement was loaded."], warnings

    kpas = getattr(contract, "kpas", {}) or {}
    kpa_codes = set(kpas.keys())

    expected_codes = {f"KPA{i}" for i in range(1, 6)}
    if director_level:
        expected_codes.add("KPA6")

    missing = sorted(expected_codes - kpa_codes)
    if missing:
        errors.append(f"Missing KPA sections: {', '.join(missing)}")

    total_weight = sum(_safe_float(getattr(kpa, "weight_pct", 0.0)) for kpa in kpas.values())
    if abs(total_weight - 100.0) > 1.0:
        errors.append(f"KPA weights total {total_weight:.2f}% (expected ≈100%).")
    elif abs(total_weight - 100.0) > 0.25:
        warnings.append(f"KPA weights total {total_weight:.2f}% (slightly off 100%).")

    for code, kpa in kpas.items():
        hours = _safe_float(getattr(kpa, "hours", 0.0))
        weight = _safe_float(getattr(kpa, "weight_pct", 0.0))
        if hours <= 0 or weight <= 0:
            errors.append(f"{code} is missing hours/weight allocations.")

        for kpi_text in _iter_kpi_text(getattr(kpa, "kpis", [])):
            lower = kpi_text.lower()
            if any(token in lower for token in MONTH_TOKENS):
                errors.append(f"{code} KPI contains month tokens: '{kpi_text}'.")
                continue
            if NAME_PLACEHOLDER_RE.search(kpi_text) or NAME_LIKE_RE.search(kpi_text):
                errors.append(f"{code} KPI appears to contain a name: '{kpi_text}'.")

    snapshot = getattr(contract, "snapshot", {}) or {}
    parse_report = snapshot.get("ta_parse_report", {}) or {}
    for section, report in parse_report.items():
        try:
            consumed = int(report.get("rows_consumed", 0) or 0)
            unconsumed = int(report.get("rows_unconsumed", 0) or 0)
        except Exception:
            continue
        total_rows = consumed + unconsumed
        if unconsumed >= 3 or (total_rows and unconsumed / total_rows >= 0.3):
            warnings.append(
                f"Section {section} has {unconsumed} unconsumed TA rows (of {total_rows})."
            )

    base_valid = bool(getattr(contract, "valid", True)) and not getattr(contract, "validation_errors", [])
    is_valid = base_valid and not errors
    return is_valid, errors, warnings


__all__ = ["validate_ta_contract"]
