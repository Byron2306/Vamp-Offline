from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional
import json

# This file lives in: backend/staff_profile.py
# So parents[0] == backend/
BASE_DIR = Path(__file__).resolve().parents[0]
CONTRACT_DIR = BASE_DIR / "data" / "contracts"
CONTRACT_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class KPI:
    """
    KPI under a KPA in the performance contract.
    """
    kpi_id: Optional[str] = None
    description: str = ""
    outputs: str = ""
    outcomes: str = ""
    weight: Optional[float] = None
    hours: Optional[float] = None
    active: bool = True


@dataclass
class KPA:
    """
    Key Performance Area – aligned with NWU KPA codes.
    """
    code: str            # e.g. "KPA1"
    name: str
    weight: Optional[float] = None
    hours: Optional[float] = None
    kpis: List[KPI] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    ta_context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StaffProfile:
    """
    A staff member's performance contract for a single year.
    """
    staff_id: str
    name: str
    position: str
    cycle_year: int
    faculty: str = ""
    line_manager: str = ""
    kpas: List[KPA] = field(default_factory=list)
    flags: List[str] = field(default_factory=list)

    @property
    def contract_path(self) -> Path:
        """
        JSON contract path: backend/data/contracts/contract_{staff_id}_{cycle_year}.json
        """
        safe_id = self.staff_id.replace("/", "-").replace("\\", "-")
        filename = f"contract_{safe_id}_{self.cycle_year}.json"
        return CONTRACT_DIR / filename

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StaffProfile":
        # Rebuild nested KPAs/KPIs
        kpas_raw = data.get("kpas", [])
        kpas: List[KPA] = []
        for k in kpas_raw:
            kpis_raw = k.get("kpis", [])
            kpis = [KPI(**kp) for kp in kpis_raw]
            kpa = KPA(
                code=k.get("code", ""),
                name=k.get("name", ""),
                weight=k.get("weight"),
                hours=k.get("hours"),
                kpis=kpis,
                context=k.get("context", {}),
                ta_context=k.get("ta_context", {}),
            )
            kpas.append(kpa)

        return cls(
            staff_id=data.get("staff_id", ""),
            name=data.get("name", ""),
            position=data.get("position", ""),
            cycle_year=int(data.get("cycle_year", 0)),
            faculty=data.get("faculty", ""),
            line_manager=data.get("line_manager", ""),
            kpas=kpas,
            flags=data.get("flags", []),
        )

    def save(self) -> None:
        """
        Persist this contract to JSON.
        """
        self.contract_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.contract_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Defaults & public API
# ---------------------------------------------------------------------------

DEFAULT_KPAS = [
    ("KPA1", "Teaching and Learning"),
    ("KPA2", "Occupational Health and Safety"),
    ("KPA3", "Research and Innovation / Creative Outputs"),
    ("KPA4", "Academic Leadership and Management"),
    ("KPA5", "Social Responsiveness / Community and Industry Engagement"),
]


def _default_kpas() -> List[KPA]:
    """
    Default empty KPA skeletons so the GUI and PA generator always
    have the 5 core NWU KPAs present.
    """
    return [
        KPA(code=code, name=name, weight=None, hours=None, kpis=[], ta_context={})
        for code, name in DEFAULT_KPAS
    ]


def create_or_load_profile(
    staff_id: str,
    name: str,
    position: str,
    cycle_year: int,
    faculty: str = "",
    line_manager: str = "",
) -> StaffProfile:
    """
    Load an existing contract if one exists for staff_id+cycle_year,
    otherwise create a new one with the 5 default KPAs.

    Used directly by the offline GUI.
    """
    profile = StaffProfile(
        staff_id=staff_id,
        name=name,
        position=position,
        cycle_year=cycle_year,
        faculty=faculty,
        line_manager=line_manager,
        kpas=[],
    )

    path = profile.contract_path
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            loaded = StaffProfile.from_dict(data)
            if not loaded.kpas:
                loaded.kpas = _default_kpas()
            return loaded
        except Exception:
            # If corrupt, fall back to fresh contract
            pass

    profile.kpas = _default_kpas()
    profile.save()
    return profile
