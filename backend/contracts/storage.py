from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from .models import StaffProfile, KPA, KPI, create_default_kpas


# ---------------------------------------------------------------------------
# Storage locations
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parents[1]  # backend/
DATA_DIR = BASE_DIR / "data"
CONTRACTS_DIR = DATA_DIR / "contracts"
CONTRACTS_DIR.mkdir(parents=True, exist_ok=True)


def contract_path(staff_id: str, cycle_year: int) -> Path:
    """Return the JSON path for a staff contract in a given year."""
    safe_id = staff_id.replace("/", "-").replace("\\", "-")
    return CONTRACTS_DIR / f"contract_{safe_id}_{cycle_year}.json"


def save_contract(profile: StaffProfile) -> Path:
    """Serialise a StaffProfile to JSON on disk and return the path."""
    path = contract_path(profile.staff_id, profile.cycle_year)
    data = profile.to_dict()
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _dict_to_profile(data: dict) -> StaffProfile:
    """Reconstruct a StaffProfile (and nested KPAs/KPIs) from raw dict."""
    kpas = []
    for kpa_data in data.get("kpas", []):
        kpis = []
        for kpi_data in kpa_data.get("kpis", []):
            kpis.append(KPI(**kpi_data))
        kpa_data = {**kpa_data, "kpis": kpis}
        kpas.append(KPA(**kpa_data))

    return StaffProfile(
        staff_id=data.get("staff_id", ""),
        name=data.get("name", ""),
        position=data.get("position", ""),
        faculty=data.get("faculty", ""),
        line_manager=data.get("line_manager", ""),
        cycle_year=int(data.get("cycle_year", 0)),
        kpas=kpas or create_default_kpas(),
    )


def load_contract(staff_id: str, cycle_year: int) -> Optional[StaffProfile]:
    """Load an existing contract, or return None if it does not exist."""
    path = contract_path(staff_id, cycle_year)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return _dict_to_profile(raw)
    except Exception as e:
        # In case of corruption, do not crash the whole app.
        print(f"⚠️ Failed to load contract {path}: {e}")
        return None


def create_or_load_profile(
    staff_id: str,
    name: str,
    position: str,
    cycle_year: int,
    faculty: str = "",
    line_manager: str = "",
) -> StaffProfile:
    """Convenience function for the GUI.

    - If a contract JSON exists for (staff_id, cycle_year), load and return it.
    - Otherwise, create a new profile with default KPAs and save it.
    """
    existing = load_contract(staff_id, cycle_year)
    if existing is not None:
        return existing

    profile = StaffProfile(
        staff_id=staff_id,
        name=name,
        position=position,
        faculty=faculty,
        line_manager=line_manager,
        cycle_year=cycle_year,
        kpas=create_default_kpas(),
    )
    save_contract(profile)
    return profile
