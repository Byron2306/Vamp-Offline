from __future__ import annotations

"""Parser for the NWU Task Agreement (TA) sheet."""

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Tuple

from openpyxl import load_workbook  # type: ignore


@dataclass
class PerformanceKPA:
    """KPA summary extracted from a Task Agreement."""

    code: str
    name: str
    hours: float
    weight_pct: float
    outputs: List = None
    kpis: List = None
    outcomes: List = None
    active: bool = True

    def __post_init__(self) -> None:
        self.outputs = [] if self.outputs is None else self.outputs
        self.kpis = [] if self.kpis is None else self.kpis
        self.outcomes = [] if self.outcomes is None else self.outcomes


@dataclass
class PerformanceContract:
    """Lightweight performance contract derived from a TA."""

    staff_id: str
    cycle_year: str
    kpas: Dict[str, PerformanceKPA]
    total_weight_pct: float
    valid: bool

    def to_dict(self) -> Dict:
        return {
            "staff_id": self.staff_id,
            "cycle_year": self.cycle_year,
            "total_weight_pct": self.total_weight_pct,
            "valid": self.valid,
            "kpas": {code: asdict(kpa) for code, kpa in self.kpas.items()},
        }


SECTION_KPA_MAP: Dict[int, Tuple[str, str]] = {
    1: ("KPA1", "Personal Research, Innovation and/or Creative Outputs"),
    2: ("KPA2", "Teaching and Learning, including Higher Degree Supervision"),
    3: ("KPA3", "Academic Leadership, Management and Administration"),
    4: ("KPA4", "Social Responsiveness and Industry Involvement"),
    5: ("KPA5", "OHS"),
    6: ("KPA6", "People Management"),
}


def _safe_float(value) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _extract_section_number(text: str) -> int | None:
    match = re.search(r"section\s*(\d+)", str(text), re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def _detect_sheet(path_to_xlsx: str):
    wb = load_workbook(filename=path_to_xlsx, data_only=True)
    if "Task Agreement Form" in wb.sheetnames:
        return wb["Task Agreement Form"], wb
    return wb[wb.sheetnames[0]], wb


def parse_nwu_ta(path_to_xlsx: str) -> PerformanceContract:
    """Parse NWU Task Agreement grand totals into a PerformanceContract."""

    ws, wb = _detect_sheet(path_to_xlsx)

    kpas: Dict[str, PerformanceKPA] = {}

    for row in ws.iter_rows(values_only=True):
        if not row or not row[0]:
            continue
        label = str(row[0]).strip()
        if not label.lower().startswith("grand total: section"):
            continue

        section_num = _extract_section_number(label)
        if section_num is None:
            continue

        mapping = SECTION_KPA_MAP.get(section_num)
        if mapping is None:
            continue

        hours = _safe_float(row[3] if len(row) > 3 else 0)
        weight_pct = _safe_float(row[4] if len(row) > 4 else 0)

        code, name = mapping
        kpa = PerformanceKPA(
            code=code,
            name=name,
            hours=hours,
            weight_pct=weight_pct,
            outputs=[],
            kpis=[],
            outcomes=[],
            active=True,
        )
        kpas[kpa.code] = kpa

    total_weight = sum(kpa.weight_pct for kpa in kpas.values())
    is_valid = abs(total_weight - 100.0) < 0.5

    # Fallback metadata if we cannot read it from the workbook properties
    staff_id = wb.properties.creator or "unknown_staff"
    cycle_year = wb.properties.created and wb.properties.created.year
    cycle_year = str(cycle_year) if cycle_year else "unknown_year"

    contract = PerformanceContract(
        staff_id=str(staff_id),
        cycle_year=cycle_year,
        kpas=kpas,
        total_weight_pct=total_weight,
        valid=is_valid,
    )

    _save_snapshot(contract)
    return contract


def _save_snapshot(contract: PerformanceContract) -> Path:
    base_dir = Path(__file__).resolve().parents[1] / "data" / "contracts"
    base_dir.mkdir(parents=True, exist_ok=True)

    safe_staff = (
        str(contract.staff_id).replace("/", "-").replace("\\", "-") or "unknown_staff"
    )
    safe_year = str(contract.cycle_year) or "unknown_year"
    out_path = base_dir / f"{safe_staff}_{safe_year}_TA.json"

    out_path.write_text(json.dumps(contract.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path
