import os
import json
import math
import re
from typing import Dict, Any, List, Tuple

import pandas as pd

# Where we stash the JSON summary that the LLM can use
EXPECT_DIR = os.path.join("backend", "data", "staff_expectations")
os.makedirs(EXPECT_DIR, exist_ok=True)

MODULE_CODE_RE = re.compile(r"[A-Z]{2,6}\s?\d{3,4}[A-Z]{0,3}")


# ----------------------------
# Helpers
# ----------------------------

def _clean_cell(v) -> str:
    """Normalise Excel cell values to a clean string."""
    if isinstance(v, float) and pd.isna(v):
        return ""
    s = str(v).strip()
    # Many cells in the FEDU template are stored as "'Text...'"
    if len(s) >= 2 and ((s[0] == "'" and s[-1] == "'") or (s[0] == '"' and s[-1] == '"')):
        s = s[1:-1]
    return s.strip()


def _safe_float(v) -> float:
    """Convert to float, treating NaN and bad values as 0."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    if isinstance(f, float) and math.isnan(f):
        return 0.0
    return f


def _extract_teaching_modules_from_addendum(xls: pd.ExcelFile) -> List[str]:
    """
    Read the Addendum B sheet (module list) and extract module codes.

    The data is attached to KPA2 as contextual metadata and does not
    affect any scoring/weight calculations.
    """

    target_sheet = None
    for name in xls.sheet_names:
        norm = name.lower().strip()
        if "addendumb" in norm and "section 2" in norm:
            target_sheet = name
            break

    if target_sheet is None:
        return []

    try:
        df_addendum = pd.read_excel(xls, sheet_name=target_sheet, header=None, dtype=str)
    except Exception:
        return []

    teaching_modules: List[str] = []
    seen: set[str] = set()

    for value in df_addendum.to_numpy().ravel():
        if pd.isna(value):
            continue
        for match in MODULE_CODE_RE.findall(str(value)):
            code = match.replace(" ", "").upper()
            if code not in seen:
                seen.add(code)
                teaching_modules.append(code)

    return teaching_modules


# Mapping of TA "SECTION X" to NWU KPA codes and names
SECTION_TO_KPA: Dict[int, Tuple[str, str]] = {
    1: ("KPA3", "Personal Research, Innovation and/or Creative Outputs"),
    2: ("KPA1", "Teaching and Learning (including supervision)"),
    3: ("KPA5", "Social Responsiveness (Community Engagement / Industry)"),
    4: ("KPA4", "Academic Leadership and Administration"),
    5: ("KPA2", "Occupational Health & Safety"),
    6: ("KPA6", "People Management"),  # not always part of the 5 KPAs, but appears in DIY form
}

# Phrases we do NOT want to treat as “tasks”
BLACKLIST_PHRASES = [
    "grand total",
    "total hours before assistance",
    "total hours of assistance",
    "total hours",
]


# ----------------------------
# Core TA parser
# ----------------------------

def parse_task_agreement(excel_path: str) -> Dict[str, Any]:
    """
    Parse the NWU FEDU Task Agreement form into a structured expectations summary.

    What we extract:
      - Per-KPA hours and approximate weight %
      - Teaching / module expectations
      - Supervision expectations
      - Research expectations
      - Leadership / committee expectations
      - Social / OHS expectations

    This implementation is tailored for the 'Task Agreement Form' sheet layout.
    """

    # Try to load the TA sheet by name first, otherwise fall back to the first sheet
    try:
        xls = pd.ExcelFile(excel_path)
        sheet_name = "Task Agreement Form"
        if sheet_name not in xls.sheet_names:
            sheet_name = xls.sheet_names[0]
        df = pd.read_excel(excel_path, sheet_name=sheet_name, header=None)
        teaching_modules = _extract_teaching_modules_from_addendum(xls)
    except Exception as e:
        print(f"[expectation_engine] Error reading TA file {excel_path}: {e}")
        return {
            "kpa_summary": {},
            "teaching": [],
            "supervision": [],
            "research": [],
            "leadership": [],
            "social": [],
            "norm_hours": 0.0,
        }

    current_section: int | None = None
    kpa_hours: Dict[str, float] = {}
    teaching: List[str] = []
    supervision: List[str] = []
    research: List[str] = []
    leadership: List[str] = []
    social: List[str] = []

    norm_hours = 0.0

    # First pass: detect Norm = 1728 hours if present
    for _, row in df.iterrows():
        cells = list(row.values)
        row_text = " ".join(_clean_cell(c) for c in cells if _clean_cell(c))
        lower = row_text.lower()
        if "norm = " in lower:
            # crude parse of the first integer in the row
            numbers = [int("".join(ch for ch in part if ch.isdigit()))
                       for part in row_text.split()
                       if any(ch.isdigit() for ch in part)]
            if numbers:
                norm_hours = float(numbers[0])
            break

    # Default to 1728 if we didn't find it
    if norm_hours <= 0:
        norm_hours = 1728.0

    # Second pass: scan sections and task rows
    for idx, row in df.iterrows():
        cells = list(row.values)
        row_text_clean = " ".join(_clean_cell(c) for c in cells if _clean_cell(c))
        row_text_lower = row_text_clean.lower()

        # --- Section detection (e.g., "SECTION 1 ... KPA: ...") ---
        if "section" in row_text_lower and "kpa" in row_text_lower:
            # Try to extract section number
            import re
            m = re.search(r"section\s*(\d+)", row_text_lower)
            if m:
                try:
                    current_section = int(m.group(1))
                except ValueError:
                    current_section = None
            else:
                current_section = None
            continue

        if current_section is None:
            # We haven't reached any SECTION yet
            continue

        # --- Hours column (in FEDU TA it's the 4th column, index 3) ---
        hours_cell = cells[3] if len(cells) > 3 else None
        hours_val = _safe_float(hours_cell)

        # Only treat rows as actual tasks if they have real hours
        if hours_val <= 0:
            continue

        # Build a "detail" string from the text columns
        detail_pieces = [cells[1] if len(cells) > 1 else "",
                         cells[0] if len(cells) > 0 else "",
                         cells[2] if len(cells) > 2 else ""]
        detail = " ".join(_clean_cell(c) for c in detail_pieces if _clean_cell(c))
        if not detail:
            continue

        dlow = detail.lower()

        # Ignore totals / meta lines
        if any(phrase in dlow for phrase in BLACKLIST_PHRASES):
            continue

        # Map section → KPA
        sec_info = SECTION_TO_KPA.get(current_section)
        if not sec_info:
            continue
        kpa_code, kpa_name = sec_info

        kpa_hours[kpa_code] = kpa_hours.get(kpa_code, 0.0) + hours_val

        # Bucket expectations by section
        pretty = f"{detail} ({hours_val:g}h)"

        if current_section == 1:
            # Research & innovation
            research.append(pretty)
        elif current_section == 2:
            # Teaching and supervision
            if "supervision" in dlow:
                supervision.append(pretty)
            else:
                teaching.append(pretty)
        elif current_section == 3:
            # Social responsiveness
            social.append(pretty)
        elif current_section in (4, 6):
            # Academic leadership & people management
            leadership.append(pretty)
        elif current_section == 5:
            # OHS – you may want to keep it separate, but
            # for now we treat it as part of "social / compliance"
            social.append(pretty)

    # Build kpa_summary with weights
    kpa_summary: Dict[str, Dict[str, Any]] = {}
    total_hours = sum(kpa_hours.values()) or norm_hours

    for sec_num, (kpa_code, kpa_name) in SECTION_TO_KPA.items():
        hours = kpa_hours.get(kpa_code, 0.0)
        if hours <= 0:
            continue
        weight_pct = round(100.0 * hours / total_hours, 1) if total_hours > 0 else 0.0
        kpa_summary[kpa_code] = {
            "name": kpa_name,
            "hours": round(hours, 2),
            "weight_pct": weight_pct,
        }

    if teaching_modules:
        kpa2_default_name = SECTION_TO_KPA.get(5, ("KPA2", "KPA2"))[1]
        kpa2_entry = kpa_summary.get("KPA2", {
            "name": kpa2_default_name,
            "hours": 0.0,
            "weight_pct": 0.0,
        })
        kpa2_entry["teaching_modules"] = teaching_modules
        kpa_summary["KPA2"] = kpa2_entry

    summary: Dict[str, Any] = {
        "norm_hours": norm_hours,
        "kpa_summary": kpa_summary,
        "teaching": teaching,
        "supervision": supervision,
        "research": research,
        "leadership": leadership,
        "social": social,
    }

    return summary


# ----------------------------
# Optional PA merge (light-touch)
# ----------------------------

def merge_with_pa(existing: Dict[str, Any], pa_path: str) -> Dict[str, Any]:
    """
    Best-effort merge with a Performance Agreement export.
    Right now, we keep this *very* conservative:

      - If PA has explicit KPA weights, we prefer those.
      - Otherwise, we leave TA-derived weights as-is.

    This avoids the previous 'int has no attribute lower' issues.
    """
    if not os.path.exists(pa_path):
        return existing

    try:
        xls = pd.ExcelFile(pa_path)
        sheet_name = xls.sheet_names[0]
        df = pd.read_excel(pa_path, sheet_name=sheet_name, header=None)
    except Exception as e:
        print(f"[expectation_engine] Error reading PA file {pa_path}: {e}")
        return existing

    # Very conservative: try to find rows that look like:
    # "Teaching and Learning", weight, hours, ...
    # and update weight_pct in existing["kpa_summary"] accordingly.

    for _, row in df.iterrows():
        cells = list(row.values)
        text = " ".join(_clean_cell(c) for c in cells if _clean_cell(c)).lower()
        if not text:
            continue

        # crude KPA detection
        kpa_code = None
        if "teaching and learning" in text:
            kpa_code = "KPA1"
        elif "research" in text and "innovation" in text:
            kpa_code = "KPA3"
        elif "academic leadership" in text or "management and administration" in text:
            kpa_code = "KPA4"
        elif "social responsiveness" in text or "industry involvement" in text:
            kpa_code = "KPA5"
        elif "occupational health" in text:
            kpa_code = "KPA2"

        if not kpa_code or kpa_code not in existing.get("kpa_summary", {}):
            continue

        # Look for an explicit weight in the numeric cells
        numeric_parts = [c for c in cells if isinstance(c, (int, float)) and not pd.isna(c)]
        if not numeric_parts:
            continue

        # Assume the first numeric is the weight percentage
        weight_pct = float(numeric_parts[0])
        existing["kpa_summary"][kpa_code]["weight_pct"] = round(weight_pct, 1)

    return existing


# ----------------------------
# Save / load / build
# ----------------------------

def save_expectations(staff_number: str, summary: Dict[str, Any]) -> str:
    """Store expectations file for LLM reference and UI."""
    out_path = os.path.join(EXPECT_DIR, f"{staff_number}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    return out_path


def load_staff_expectations(staff_number: str) -> Dict[str, Any]:
    """Load expectations summary JSON if available."""
    path = os.path.join(EXPECT_DIR, f"{staff_number}.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_staff_expectations(staff_number: str, ta_path: str, pa_path: str | None = None) -> Dict[str, Any]:
    """
    Full pipeline used by the UI after TA import and optional PA generation:

      1. Parse TA into structured expectations.
      2. Merge with PA (if available) to refine KPA weights.
      3. Save JSON to backend/data/staff_expectations/{staff_number}.json
    """
    summary = parse_task_agreement(ta_path)
    if pa_path:
        summary = merge_with_pa(summary, pa_path)

    save_expectations(staff_number, summary)
    return summary


# ----------------------------
# Pretty-print for the UI
# ----------------------------

def format_expectations_summary(summary: Dict[str, Any]) -> str:
    """
    Turn the summary dict into the compact, human-readable block you see in the UI.
    This replaces the previous behaviour where we dumped half the template.
    """
    if not summary:
        return "No Task Agreement / Performance Agreement expectations found."

    lines: List[str] = []

    # KPA overview
    lines.append("KPA weightings & hours:")
    kpa_summary = summary.get("kpa_summary", {})
    if not kpa_summary:
        lines.append(" • (No KPAs found in agreements)")
    else:
        # Stable ordering by KPA code
        for code in sorted(kpa_summary.keys()):
            info = kpa_summary[code]
            name = info.get("name", code)
            hours = info.get("hours", 0.0)
            weight = info.get("weight_pct", 0.0)
            lines.append(f" • {code} – {name}: {hours:g} hours (~{weight:.1f}%)")

    # Teaching
    lines.append("\nTeaching / modules:")
    teaching = summary.get("teaching", [])
    if teaching:
        for item in teaching[:8]:
            lines.append(f" • {item}")
        if len(teaching) > 8:
            lines.append(f" • (+{len(teaching) - 8} more teaching items)")
    else:
        lines.append(" • (No modules specified with hours)")

    teaching_modules = (
        summary.get("kpa_summary", {})
        .get("KPA2", {})
        .get("teaching_modules", [])
    )
    if teaching_modules:
        preview = ", ".join(teaching_modules[:8])
        extra = len(teaching_modules) - 8
        suffix = f" (+{extra} more)" if extra > 0 else ""
        lines.append(f" • Modules (Addendum B): {preview}{suffix}")

    # Supervision
    lines.append("\nSupervision expectations:")
    supervision = summary.get("supervision", [])
    if supervision:
        for item in supervision[:6]:
            lines.append(f" • {item}")
        if len(supervision) > 6:
            lines.append(f" • (+{len(supervision) - 6} more supervision items)")
    else:
        lines.append(" • (None specified)")

    # Research
    lines.append("\nResearch expectations:")
    research = summary.get("research", [])
    if research:
        for item in research[:6]:
            lines.append(f" • {item}")
        if len(research) > 6:
            lines.append(f" • (+{len(research) - 6} more research items)")
    else:
        lines.append(" • (None specified)")

    # Social
    lines.append("\nSocial responsiveness expectations:")
    social = summary.get("social", [])
    if social:
        for item in social[:6]:
            lines.append(f" • {item}")
        if len(social) > 6:
            lines.append(f" • (+{len(social) - 6} more social/OHS items)")
    else:
        lines.append(" • (None specified)")

    # Leadership
    lines.append("\nLeadership / committee roles:")
    leadership = summary.get("leadership", [])
    if leadership:
        for item in leadership[:8]:
            lines.append(f" • {item}")
        if len(leadership) > 8:
            lines.append(f" • (+{len(leadership) - 8} more leadership items)")
    else:
        lines.append(" • (None specified)")

    return "\n".join(lines)
