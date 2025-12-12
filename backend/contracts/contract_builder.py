from __future__ import annotations

"""Merge Task Agreement (TA) and Performance Agreement (PA) data into a
canonical performance contract.

Rules (Batch 4)
---------------
* Hours and Weight always come from the Task Agreement (TA).
* Outputs, KPIs and Outcomes are taken from the Performance Agreement (PA).
* If no PA data is available for a staff member, the TA values are preserved
  but the final contract is flagged with ``kpis_missing=True``.
* KPA names between TA and PA are matched fuzzily to tolerate minor wording
  differences.
"""

from dataclasses import asdict, dataclass
from difflib import get_close_matches
from pathlib import Path
from typing import Dict, Iterable, Optional
import json

from backend.nwu_formats.ta_parser import PerformanceContract as TAPerformanceContract
from backend.contracts.kpi_generator import generate_kpis_from_outputs


@dataclass
class MergedKPA:
    """Canonical representation of a KPA in the merged contract."""

    code: str
    name: str
    hours: float
    weight_pct: float
    outputs: object
    kpis: object
    outcomes: object
    active: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PerformanceContract:
    """Final performance contract after merging TA and PA inputs."""

    staff_id: str
    cycle_year: str
    kpas: Dict[str, MergedKPA]
    total_weight_pct: float
    valid: bool
    kpis_missing: bool = False
    kpis_generated: bool = False

    def to_dict(self) -> dict:
        return {
            "staff_id": self.staff_id,
            "cycle_year": self.cycle_year,
            "total_weight_pct": self.total_weight_pct,
            "valid": self.valid,
            "kpis_missing": self.kpis_missing,
            "kpis_generated": self.kpis_generated,
            "kpas": {code: kpa.to_dict() for code, kpa in self.kpas.items()},
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalise_name(name: str) -> str:
    return " ".join(name.lower().split())


def _find_pa_match(kpa_name: str, pa_names: Iterable[str]) -> Optional[str]:
    """Return the closest PA KPA name for the given TA KPA name."""

    normalised = _normalise_name(kpa_name)
    choices = list(pa_names)
    if not choices:
        return None

    matches = get_close_matches(normalised, [_normalise_name(c) for c in choices], n=1, cutoff=0.6)
    if not matches:
        return None

    matched_norm = matches[0]
    for original in choices:
        if _normalise_name(original) == matched_norm:
            return original
    return None


def _extract_field(pa_row: Dict[str, object], target_substring: str, default: object = "") -> object:
    """Pick a field from a PA row using case-insensitive substring matching."""

    for key, value in pa_row.items():
        if target_substring.lower() in key.lower():
            return value
    return default


def _extract_active(pa_row: Dict[str, object]) -> bool:
    flag = _extract_field(pa_row, "active", default="Y")
    if isinstance(flag, str):
        return flag.strip().lower() in {"y", "yes", "true", "1"}
    if isinstance(flag, (int, float)):
        return bool(flag)
    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_final_contract(ta_contract: TAPerformanceContract, pa_data: Optional[Dict[str, Dict[str, object]]]) -> PerformanceContract:
    """Merge TA and PA data into a final canonical PerformanceContract."""

    pa_data = pa_data or {}
    kpas: Dict[str, MergedKPA] = {}
    matched_any = False
    kpis_generated = False

    for ta_kpa in ta_contract.kpas.values():
        pa_match_name = _find_pa_match(ta_kpa.name, pa_data.keys()) if pa_data else None
        pa_row = pa_data.get(pa_match_name, {}) if pa_match_name else {}
        matched_any = matched_any or bool(pa_row)

        outputs = _extract_field(pa_row, "output", default=ta_kpa.outputs)
        kpis = _extract_field(pa_row, "kpi", default=ta_kpa.kpis)
        if (not kpis or kpis == "") and outputs:
            kpis = generate_kpis_from_outputs(outputs)
            kpis_generated = True

        merged_kpa = MergedKPA(
            code=ta_kpa.code,
            name=ta_kpa.name,
            hours=ta_kpa.hours,
            weight_pct=ta_kpa.weight_pct,
            outputs=outputs,
            kpis=kpis,
            outcomes=_extract_field(pa_row, "outcome", default=ta_kpa.outcomes),
            active=_extract_active(pa_row) if pa_row else ta_kpa.active,
        )
        kpas[merged_kpa.code] = merged_kpa

    total_weight = sum(k.weight_pct for k in ta_contract.kpas.values())
    contract = PerformanceContract(
        staff_id=str(ta_contract.staff_id),
        cycle_year=str(ta_contract.cycle_year),
        kpas=kpas,
        total_weight_pct=total_weight,
        valid=ta_contract.valid,
        kpis_missing=not matched_any,
        kpis_generated=kpis_generated,
    )
    return contract


def save_final_contract(contract: PerformanceContract) -> Path:
    """Persist the merged contract to backend/data/contracts/<staff>_<year>_FINAL.json."""

    base_dir = Path(__file__).resolve().parents[1] / "data" / "contracts"
    base_dir.mkdir(parents=True, exist_ok=True)

    safe_staff = str(contract.staff_id).replace("/", "-").replace("\\", "-") or "unknown_staff"
    safe_year = str(contract.cycle_year) or "unknown_year"
    out_path = base_dir / f"{safe_staff}_{safe_year}_FINAL.json"

    out_path.write_text(json.dumps(contract.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path
