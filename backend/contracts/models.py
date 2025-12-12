from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Canonical KPA definitions for NWU academic staff
# ---------------------------------------------------------------------------

KPA_DEFINITIONS: Dict[str, str] = {
    "KPA1": "Teaching and Learning, including Higher Degree Supervision",
    "KPA2": "OHS (Occupational Health and Safety)",
    "KPA3": "Personal Research, Innovation and/or Creative Outputs",
    "KPA4": "Academic Leadership, Management and Administration",
    "KPA5": "Social Responsiveness and Industry Involvement",
}


@dataclass
class KPI:
    """Key Performance Indicator for a single staff member in a given KPA.

    This is intentionally simple for Batch 1. Later batches can extend it with
    things like explicit links to NWU values, promotion criteria, etc.
    """

    id: str
    description: str
    outputs: str = """"""  # basic quantitative measures staff or AI can fill in
    outcomes: str = """"""  # values- and impact-focused outcomes (to be filled over time)
    values_tags: List[str] = field(default_factory=list)
    measure: str = ""
    target: str = ""
    due: str = ""
    evidence_types: List[str] = field(default_factory=list)
    generated_by_ai: bool = False
    active: bool = True
    weight: float = 0.0  # % weight within its KPA (optional, not enforced yet)
    hours: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class KPA:
    """A Key Performance Area in the NWU performance system."""

    code: str  # e.g. "KPA1"
    name: str
    weight: float = 0.0  # overall KPA weight in the PA (%)
    hours: float = 0.0   # total hours allocated in the contract year
    kpis: List[KPI] = field(default_factory=list)
    ta_context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        data = asdict(self)
        return data


@dataclass
class StaffProfile:
    """Per-staff "contract brain" for a given performance cycle.

    Batch 1 keeps this intentionally small and JSON-friendly. It mirrors the
    information that appears in the Task Agreement and Performance Agreement
    templates, but without binding to any particular Excel layout.
    """

    staff_id: str
    name: str
    position: str  # e.g. "Junior Lecturer", "Senior Lecturer", "Professor"
    faculty: str = ""
    line_manager: str = ""
    cycle_year: int = 0
    kpas: List[KPA] = field(default_factory=list)
    flags: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def create_default_kpas() -> List[KPA]:
    """Create an empty KPA skeleton using the canonical NWU KPA list.

    This gives a reasonable starting point when enrolling a staff member before
    importing a Task Agreement. The import step can then enrich / overwrite the
    KPI lists and weights.
    """
    kpas: List[KPA] = []
    for code, name in KPA_DEFINITIONS.items():
        kpas.append(KPA(code=code, name=name))
    return kpas
