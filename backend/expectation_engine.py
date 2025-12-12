import json
import math
import os
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

# Where we stash the JSON summary that the LLM can use
EXPECT_DIR = os.path.join("backend", "data", "staff_expectations")
os.makedirs(EXPECT_DIR, exist_ok=True)

MODULE_CODE_RE = re.compile(r"[A-Z]{2,6}\s?\d{3,4}[A-Z]{0,3}")
MONTH_TOKENS = {
    "jan",
    "january",
    "feb",
    "february",
    "mar",
    "march",
    "apr",
    "april",
    "may",
    "jun",
    "june",
    "jul",
    "july",
    "aug",
    "august",
    "sep",
    "sept",
    "september",
    "oct",
    "october",
    "nov",
    "november",
    "dec",
    "december",
}
XML_NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


# ----------------------------
# Helpers
# ----------------------------

def _clean_cell(v) -> str:
    """Normalise Excel cell values to a clean string."""

    if v is None:
        return ""
    if isinstance(v, float) and math.isnan(v):
        return ""

    s = str(v).replace("_x000D_", "\n").replace("\r", "\n").strip()
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


def _load_shared_strings(zf: zipfile.ZipFile) -> List[str]:
    try:
        xml_data = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []

    root = ET.fromstring(xml_data)
    shared: List[str] = []
    for si in root.findall("main:si", XML_NS):
        text_parts = [t.text or "" for t in si.findall(".//main:t", XML_NS)]
        shared.append("".join(text_parts))
    return shared


def _workbook_sheets(zf: zipfile.ZipFile) -> List[Tuple[str, str]]:
    """Return list of (sheet_name, target_path) pairs."""

    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    sheets_parent = workbook.find("main:sheets", XML_NS)
    if sheets_parent is None:
        return []

    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rel_map = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}

    sheets: List[Tuple[str, str]] = []
    for sheet in sheets_parent.findall("main:sheet", XML_NS):
        rel_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        target = rel_map.get(rel_id, "")
        if target:
            sheets.append((sheet.attrib.get("name", ""), f"xl/{target}"))
    return sheets


def _col_to_index(col_letters: str) -> int:
    total = 0
    for ch in col_letters:
        total = total * 26 + (ord(ch.upper()) - ord("A") + 1)
    return max(total - 1, 0)


def _extract_month_tokens(text: str) -> List[str]:
    """Return canonical month tokens detected in a cell value."""

    tokens: List[str] = []
    lowered = text.lower()
    for part in re.split(r"[^A-Za-z/]+", lowered):
        if not part:
            continue
        for candidate in part.split("/"):
            if candidate and candidate in MONTH_TOKENS:
                tokens.append(candidate.title())
    return tokens


def _iter_sheet_rows(zf: zipfile.ZipFile, sheet_path: str, shared: List[str]) -> Iterable[List[str]]:
    sheet = ET.fromstring(zf.read(sheet_path))
    for row in sheet.findall("main:sheetData/main:row", XML_NS):
        values: Dict[int, str] = {}
        for cell in row.findall("main:c", XML_NS):
            ref = cell.attrib.get("r", "")
            col_letters = "".join(ch for ch in ref if ch.isalpha())
            col_idx = _col_to_index(col_letters)
            cell_type = cell.attrib.get("t")
            value_el = cell.find("main:v", XML_NS)
            raw_value = value_el.text if value_el is not None else None

            if cell_type == "s":
                resolved = shared[int(raw_value)] if raw_value is not None else ""
            elif cell_type == "inlineStr":
                inline = cell.find("main:is", XML_NS)
                resolved = "".join(t_el.text or "" for t_el in inline.findall(".//main:t", XML_NS)) if inline is not None else ""
            else:
                resolved = raw_value or ""

            values[col_idx] = _clean_cell(resolved)

        if values:
            max_idx = max(values)
            row_data = [values.get(i, "") for i in range(max_idx + 1)]
            yield row_data


def _extract_teaching_modules_from_addendum(sheets: List[Tuple[str, str]], zf: zipfile.ZipFile, shared: List[str]) -> List[str]:
    target_sheet: Tuple[str, str] | None = None
    for name, target in sheets:
        norm = name.lower().strip()
        if "addendumb" in norm and "section 2" in norm:
            target_sheet = (name, target)
            break

    if target_sheet is None:
        return []

    _, sheet_path = target_sheet
    teaching_modules: List[str] = []
    seen: set[str] = set()

    for row in _iter_sheet_rows(zf, sheet_path, shared):
        for value in row:
            if not value:
                continue
            for match in MODULE_CODE_RE.findall(value):
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

    path = Path(excel_path)
    if not path.exists():
        raise FileNotFoundError(excel_path)

    try:
        with zipfile.ZipFile(path) as zf:
            shared = _load_shared_strings(zf)
            sheets = _workbook_sheets(zf)
            if not sheets:
                raise ValueError("No sheets found in workbook")

            ta_sheet_path = sheets[0][1]
            for name, target in sheets:
                if name.strip().lower() == "task agreement form":
                    ta_sheet_path = target
                    break

            rows = list(_iter_sheet_rows(zf, ta_sheet_path, shared))
            teaching_modules = _extract_teaching_modules_from_addendum(sheets, zf, shared)
    except Exception as e:
        print(f"[expectation_engine] Error reading TA file {excel_path}: {e}")
        return {
            "kpa_summary": {},
            "teaching": [],
            "supervision": [],
            "research": [],
            "leadership": [],
            "social": [],
            "ohs": [],
            "norm_hours": 0.0,
            "teaching_modules": [],
            "teaching_practice_windows": [],
            "ta_parse_report": {},
        }

    current_section: int | None = None
    kpa_hours: Dict[str, float] = {}
    teaching: List[str] = []
    supervision: List[str] = []
    research: List[str] = []
    leadership: List[str] = []
    social: List[str] = []
    teaching_practice_windows: List[str] = []
    ohs: List[str] = []

    ta_parse_report: Dict[int, Dict[str, object]] = {}
    current_block: str | None = None

    norm_hours = 0.0

    # First pass: detect Norm = 1728 hours if present
    for row in rows:
        row_text = " ".join(_clean_cell(c) for c in row if _clean_cell(c))
        lower = row_text.lower()
        if "norm = " in lower:
            numbers = [
                int("".join(ch for ch in part if ch.isdigit()))
                for part in row_text.split()
                if any(ch.isdigit() for ch in part)
            ]
            if numbers:
                norm_hours = float(numbers[0])
            break

    # Default to 1728 if we didn't find it
    if norm_hours <= 0:
        norm_hours = 1728.0

    # Second pass: scan sections and task rows
    for row in rows:
        cells = row
        row_text_clean = " ".join(_clean_cell(c) for c in cells if _clean_cell(c))
        row_text_lower = row_text_clean.lower()

        # --- Section detection (e.g., "SECTION 1 ... KPA: ...") ---
        if "section" in row_text_lower and "kpa" in row_text_lower:
            m = re.search(r"section\s*(\d+)", row_text_lower)
            if m:
                try:
                    current_section = int(m.group(1))
                except ValueError:
                    current_section = None
            else:
                current_section = None
            if current_section is not None:
                ta_parse_report.setdefault(
                    current_section,
                    {
                        "blocks_detected": set(),
                        "rows_consumed": 0,
                        "rows_unconsumed": 0,
                        "unconsumed_examples": [],
                    },
                )
            current_block = None
            continue

        if current_section is None:
            continue

        # Detect block headers within a section (e.g. supervision tables, WIL months)
        lowered = row_text_lower
        new_block = None
        if "supervision" in lowered:
            new_block = "supervision"
        elif "practical teaching" in lowered or ("wil" in lowered and "teaching" in lowered):
            new_block = "teaching_practice_windows"
        elif "module code" in lowered and "number of students" in lowered:
            new_block = "module_table"
        elif "committee" in lowered or "meetings" in lowered:
            new_block = "committee_roles"
        elif "research" in lowered and "section" not in lowered:
            new_block = "research_block"
        elif "occupational health" in lowered or "ohs" in lowered:
            new_block = "ohs_block"

        if new_block:
            if current_block == "supervision" and new_block == "module_table":
                pass
            else:
                current_block = new_block

        if current_block and current_section is not None:
            ta_parse_report.setdefault(current_section, {"blocks_detected": set(), "rows_consumed": 0, "rows_unconsumed": 0, "unconsumed_examples": []})
            ta_parse_report[current_section]["blocks_detected"].add(current_block)

        # --- Hours column (in FEDU TA it's the 4th column, index 3) ---
        hours_cell = cells[3] if len(cells) > 3 else None
        hours_val = _safe_float(hours_cell)

        # Only treat rows as actual tasks if they have real hours
        if hours_val <= 0:
            continue

        # Build a "detail" string from the text columns
        detail_pieces = [cells[1] if len(cells) > 1 else "", cells[0] if len(cells) > 0 else "", cells[2] if len(cells) > 2 else ""]
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

        consumed = False
        if current_block == "supervision":
            if MODULE_CODE_RE.search(detail):
                teaching.append(detail)
            else:
                supervision.append(detail)
            consumed = True
        elif current_block == "teaching_practice_windows":
            months = _extract_month_tokens(detail)
            if months:
                teaching_practice_windows.extend(months)
                consumed = True
            else:
                teaching.append(detail)
                consumed = True
        elif current_block == "module_table":
            teaching.append(detail)
            consumed = True
        elif current_block == "committee_roles":
            leadership.append(detail)
            consumed = True
        elif current_block == "research_block":
            research.append(detail)
            consumed = True
        elif current_block == "ohs_block":
            ohs.append(detail)
            consumed = True
        else:
            # Attach detail to relevant list using default mapping
            if kpa_code == "KPA1":
                teaching.append(detail)
                consumed = True
            elif kpa_code == "KPA2":
                ohs.append(detail)
                consumed = True
            elif kpa_code == "KPA3":
                research.append(detail)
                consumed = True
            elif kpa_code == "KPA4":
                leadership.append(detail)
                consumed = True
            elif kpa_code == "KPA5":
                social.append(detail)
                consumed = True
            elif kpa_code == "KPA6":
                leadership.append(detail)
                consumed = True

        if current_section is not None:
            ta_parse_report.setdefault(
                current_section,
                {"blocks_detected": set(), "rows_consumed": 0, "rows_unconsumed": 0, "unconsumed_examples": []},
            )
            if consumed:
                ta_parse_report[current_section]["rows_consumed"] += 1
            else:
                ta_parse_report[current_section]["rows_unconsumed"] += 1
                examples = ta_parse_report[current_section]["unconsumed_examples"]
                if isinstance(examples, list) and len(examples) < 5:
                    examples.append(detail)

    # Convert hours to weight %
    total_hours = sum(kpa_hours.values())
    if total_hours <= 0:
        total_hours = 1.0

    kpa_summary: Dict[str, Dict[str, float | str]] = {}
    for code, name in SECTION_TO_KPA.values():
        hours = kpa_hours.get(code, 0.0)
        if hours <= 0 and not (code == "KPA2" and teaching_modules):
            continue
        kpa_summary[code] = {
            "name": name,
            "hours": hours,
            "weight_pct": round((hours / total_hours) * 100, 2) if total_hours else 0.0,
        }
        if code == "KPA2" and teaching_modules:
            kpa_summary[code]["teaching_modules"] = teaching_modules

    for report in ta_parse_report.values():
        if isinstance(report.get("blocks_detected"), set):
            report["blocks_detected"] = sorted(report["blocks_detected"])  # type: ignore[index]

    return {
        "kpa_summary": kpa_summary,
        "teaching": teaching,
        "supervision": supervision,
        "research": research,
        "leadership": leadership,
        "social": social,
        "ohs": ohs,
        "norm_hours": norm_hours,
        "teaching_modules": teaching_modules,
        "teaching_practice_windows": teaching_practice_windows,
        "ta_parse_report": ta_parse_report,
    }


# ----------------------------
# CLI utility for manual inspection
# ----------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Parse NWU TA expectations")
    parser.add_argument("excel_path", help="Path to the Excel TA file")
    args = parser.parse_args()

    summary = parse_task_agreement(args.excel_path)
    out_path = Path(EXPECT_DIR) / f"{Path(args.excel_path).stem}_summary.json"
    out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved summary to {out_path}")
