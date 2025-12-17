from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, List, Any

# ---------------------------------------------------------------------------
# Evidence logging configuration
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parents[1]  # backend/
DATA_DIR = BASE_DIR / "data"
EVIDENCE_DIR = DATA_DIR / "evidence"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

# Canonical column order for the longitudinal evidence log
EVIDENCE_COLUMNS: List[str] = [
    "staff_id",
    "cycle_year",
    "month_bucket",
    "file_path",
    "file_name",
    "file_sha1",
    "kpa_code",
    "kpa_name",
    "kpi_id",
    "kpi_description",
    "rating",
    "rating_label",
    "impact_summary",
    "risks_or_gaps",
    "values_hits",
    "evidence_type",
    "raw_llm_json",
]


def evidence_csv_path(staff_id: str, cycle_year: int) -> Path:
    """Return the path for a staff/year evidence CSV.

    One file per staff member per cycle year. This is the core longitudinal
    log that later batches (mid-year / final aggregation) will read from.
    """
    safe_id = staff_id.replace("/", "-").replace("\\", "-")
    filename = f"evidence_{safe_id}_{cycle_year}.csv"
    return EVIDENCE_DIR / filename


def append_evidence_row(staff_id: str, cycle_year: int, row: Dict[str, Any]) -> Path:
    """Append a single evidence row to the per-staff/year CSV.

    `row` is a dict; any missing keys are filled with empty strings to keep
    the file rectangular. Values are stringified on write.
    """
    path = evidence_csv_path(staff_id, cycle_year)
    new_file = not path.is_file()

    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(EVIDENCE_COLUMNS)

        out_row: List[str] = []
        for col in EVIDENCE_COLUMNS:
            value = row.get(col, "")
            if value is None:
                value_str = ""
            else:
                value_str = str(value)
            out_row.append(value_str)

        writer.writerow(out_row)

    return path
