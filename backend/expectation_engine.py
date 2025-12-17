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


def _fold_people_management_summary(
    summary: Dict[str, Any], director_level: bool
) -> Dict[str, Any]:
    """Merge People Management into KPA4 for ordinary staff."""

    if director_level:
        return summary or {}

    merged = dict(summary or {})
    kpa_summary = dict(merged.get("kpa_summary") or {})
    people_management = list(merged.get("people_management") or [])

    pm_block = kpa_summary.pop("KPA6", None)
    if pm_block:
        kpa4 = dict(kpa_summary.get("KPA4") or {})
        kpa4_hours = _safe_float(kpa4.get("hours")) + _safe_float(pm_block.get("hours"))
        kpa4_weight = _safe_float(kpa4.get("weight_pct")) + _safe_float(
            pm_block.get("weight_pct")
        )

        if not kpa4.get("name"):
            kpa4["name"] = pm_block.get(
                "name", "Academic Leadership and Administration"
            )

        kpa4["hours"] = kpa4_hours
        kpa4["weight_pct"] = kpa4_weight
        kpa_summary["KPA4"] = kpa4

    merged["kpa_summary"] = kpa_summary
    if people_management:
        merged["people_management"] = people_management
    return merged


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

def parse_task_agreement(excel_path: str, director_level: bool = False) -> Dict[str, Any]:
    """
    Parse the NWU FEDU Task Agreement form into a structured expectations summary.

    What we extract:
      - Per-KPA hours and approximate weight % (KPA6 is folded into KPA4 for
        ordinary staff)
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
            "warnings": [f"TA parse failed: {e}"],
            "total_hours": 0.0,
        }

    current_section: int | None = None
    kpa_hours: Dict[str, float] = {}
    teaching: List[str] = []
    supervision: List[str] = []
    research: List[str] = []
    leadership: List[str] = []
    people_management: List[str] = []
    social: List[str] = []
    teaching_practice_windows: List[str] = []
    ohs: List[str] = []

    ta_parse_report: Dict[int, Dict[str, object]] = {}
    current_block: str | None = None

    warnings: List[str] = []
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

        # Teaching Practice Assessment rows sometimes contain only month windows
        # (e.g., "April / July"). Do not treat those as targets or people names –
        # always bucket them as practice windows when hours are present.
        month_tokens = _extract_month_tokens(detail)
        if month_tokens and (
            current_block == "teaching_practice_windows"
            or "teaching practice" in dlow
            or "practice assessment" in dlow
        ):
            teaching_practice_windows.extend(month_tokens)
            consumed = True
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
                ta_parse_report[current_section]["rows_consumed"] += 1
            continue

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
            months = month_tokens or _extract_month_tokens(detail)
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
                people_management.append(detail)
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

    # Fold KPA6 into KPA4 for ordinary staff so downstream UI never shows a
    # People Management KPA unless the profile is flagged as director-level.
    folded_summary = _fold_people_management_summary(
        {
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
            "people_management": people_management,
            "ta_parse_report": ta_parse_report,
        },
        director_level,
    )

    total_hours = sum(v.get("hours", 0.0) for v in folded_summary.get("kpa_summary", {}).values())
    if norm_hours and total_hours > norm_hours:
        warnings.append(
            f"Over-norm workload: +{total_hours - norm_hours:.1f} hours"
        )

    for report in ta_parse_report.values():
        if isinstance(report.get("blocks_detected"), set):
            report["blocks_detected"] = sorted(report["blocks_detected"])  # type: ignore[index]

    folded_summary["warnings"] = warnings
    folded_summary["total_hours"] = total_hours
    return folded_summary


# ----------------------------
# Build full expectations from TA
# ----------------------------

def build_expectations_from_ta(staff_id: str, year: int, ta_summary: Dict[str, Any]) -> Dict[str, Any]:
    """Build comprehensive expectations structure from TA summary.
    
    Generates monthly tasks for all 5 KPAs with lead/lag indicators and evidence hints.
    """
    kpa_summary = ta_summary.get("kpa_summary", {})
    teaching = ta_summary.get("teaching", [])
    research = ta_summary.get("research", [])
    leadership = ta_summary.get("leadership", [])
    social = ta_summary.get("social", [])
    ohs = ta_summary.get("ohs", [])
    practice_windows = ta_summary.get("teaching_practice_windows", [])
    
    # Ensure all 5 KPAs exist in summary (add missing ones with zero hours)
    standard_kpas = {
        "KPA1": "Teaching and Learning (including supervision)",
        "KPA2": "Occupational Health & Safety",
        "KPA3": "Personal Research, Innovation and/or Creative Outputs",
        "KPA4": "Academic Leadership and Administration",
        "KPA5": "Social Responsiveness (Community Engagement / Industry)"
    }
    
    for code, name in standard_kpas.items():
        if code not in kpa_summary:
            kpa_summary[code] = {"name": name, "hours": 0.0, "weight_pct": 0.0}
    
    # Generate monthly tasks for each KPA
    tasks: List[Dict[str, Any]] = []
    task_counter = 1

    def _kpa_default_evidence(kpa_code: str) -> List[str]:
        if kpa_code == "KPA1":
            return [
                "lesson plan / teaching plan",
                "lecture slides / notes",
                "LMS (eFundi) screenshots or exports",
                "assessment brief / rubric",
                "mark sheet / gradebook export",
                "moderation report / internal moderation evidence",
                "student feedback / reflection",
            ]
        if kpa_code == "KPA2":
            return [
                "OHS checklist / inspection evidence",
                "training certificate",
                "compliance communication",
                "incident/near-miss report (if applicable)",
            ]
        if kpa_code == "KPA3":
            return [
                "manuscript draft / tracked changes",
                "submission confirmation / email",
                "ethics application / approval",
                "grant application pack",
                "conference submission / acceptance",
                "research report / progress log",
            ]
        if kpa_code == "KPA4":
            return [
                "meeting agenda / minutes",
                "committee report / decision memo",
                "planning document",
                "QA / review notes",
                "emails confirming actions/approvals",
            ]
        if kpa_code == "KPA5":
            return [
                "event programme / flyer",
                "attendance register",
                "stakeholder correspondence",
                "MoU / engagement letter",
                "reflection / impact note",
            ]
        return ["supporting document", "screenshot / export", "email confirmation"]

    def _what_to_do(kpa_code: str, title: str, outputs: str) -> str:
        t = (title or "").lower()
        if kpa_code == "KPA1":
            if "prep" in t:
                return "Prepare module materials, update LMS (eFundi), and confirm schedules/readings."
            if "start" in t:
                return "Launch the semester: onboarding/orientation, first lectures, and initial assessments."
            if "mid-term" in t or "mid term" in t:
                return "Run mid-term assessments and provide feedback/interventions where needed."
            if "exams" in t or "exam" in t:
                return "Set/invigilate assessments, mark scripts, and submit grades according to deadlines."
            if "marks" in t or "moderation" in t or "quality assurance" in t:
                return "Finalise marks, complete moderation/QA, and store evidence of compliance and quality."
            return "Deliver teaching activities and capture evidence of delivery, assessment, and learner support."
        if kpa_code == "KPA2":
            return "Complete the compliance activity and retain proof (checklists, certificates, or emails)."
        if kpa_code == "KPA3":
            if "ethics" in t:
                return "Prepare and submit ethics documentation or track approval progress."
            if "grant" in t or "nrf" in t or "rating" in t:
                return "Prepare and submit the application package; keep submission confirmations."
            if "publication" in t or "manuscript" in t:
                return "Draft/revise a manuscript and progress it through submission or review stages."
            if "supervision" in t:
                return "Hold supervision meetings, track milestones, and file progress notes."
            return "Advance research outputs and keep artefacts showing progress and submissions."
        if kpa_code == "KPA4":
            return "Complete the admin/leadership activity and retain minutes, reports, and approvals."
        if kpa_code == "KPA5":
            return "Deliver the engagement activity and retain proof of participation and impact."
        return outputs or "Complete the activity and retain supporting evidence."

    def _evidence_required(kpa_code: str, evidence_hints: List[str], outputs: str) -> str:
        base = _kpa_default_evidence(kpa_code)
        # Keep hints readable; avoid dumping huge module strings as a single 'hint'
        hints = [h for h in (evidence_hints or []) if isinstance(h, str) and len(h.strip()) > 0]
        # De-dup while preserving order
        seen: set[str] = set()
        combined: List[str] = []
        for item in base + hints:
            norm = item.strip()
            if not norm:
                continue
            key = norm.lower()
            if key in seen:
                continue
            seen.add(key)
            combined.append(norm)
        if outputs:
            combined.insert(0, f"Output evidence: {outputs}")
        # Limit length for UI readability
        return "; ".join(combined[:10])
    
    # KPA1: Teaching (NWU 2025 Academic Calendar aligned)
    kpa1_hours = kpa_summary.get("KPA1", {}).get("hours", 0.0)
    
    # Extract teaching modules from TA
    teaching_modules = []
    for item in teaching:
        module_matches = MODULE_CODE_RE.findall(item)
        teaching_modules.extend(module_matches)
    
    teaching_modules_str = ", ".join(set(teaching_modules)) if teaching_modules else "Teaching modules as per TA"
    
    if kpa1_hours > 0:
        # NWU 2025 Calendar milestones
        nwu_calendar = {
            1: {"period": "Semester 1 Prep", "tasks": ["Module preparation", "eFundi setup", "Study guide finalization"]},
            2: {"period": "Semester 1 Start", "tasks": ["Orientation week", "First lectures", "Student onboarding"]},
            3: {"period": "Semester 1 Teaching", "tasks": ["Regular lectures", "Formative assessments", "Tutorial support"]},
            4: {"period": "Semester 1 Mid-term", "tasks": ["Mid-term assessments", "Student feedback", "Remedial interventions"]},
            5: {"period": "Semester 1 Completion", "tasks": ["Final lectures", "Semester tests", "Exam prep workshops"]},
            6: {"period": "Semester 1 Exams", "tasks": ["Exam invigilation", "Marking", "Grade submission"]},
            7: {"period": "Mid-Year Break", "tasks": ["Semester 2 planning", "Module revisions", "Research time"]},
            8: {"period": "Semester 2 Start", "tasks": ["Welcome back", "Semester 2 lectures begin", "Assessment schedules"]},
            9: {"period": "Semester 2 Teaching", "tasks": ["Regular lectures", "Formative assessments", "Tutorial support"]},
            10: {"period": "Semester 2 Mid-term", "tasks": ["Mid-term assessments", "Student feedback", "Remedial interventions"]},
            11: {"period": "Semester 2 Completion", "tasks": ["Final lectures", "Semester tests", "Exam prep workshops"]},
            12: {"period": "Year-End Exams", "tasks": ["Exam invigilation", "Final marking", "Moderation", "Grade finalization"]}
        }
        
        for month in range(1, 13):
            period_info = nwu_calendar.get(month, {"period": "Teaching", "tasks": []})
            task_title = f"{period_info['period']}: {teaching_modules_str}"
            task_description = " | ".join(period_info['tasks'][:2])
            
            tasks.append({
                "id": f"task_{task_counter:03d}",
                "kpa_code": "KPA1",
                "kpa_name": "Teaching and Learning",
                "title": task_title,
                "cadence": "monthly",
                "months": [month],
                "minimum_count": 3 if month in [2,3,4,5,8,9,10,11] else 2,  # Higher expectations during teaching months
                "stretch_count": 5 if month in [2,3,4,5,8,9,10,11] else 3,
                "evidence_hints": ["lecture", "assessment", "efundi", "lms", "class", "tutorial", "marks", teaching_modules_str],
                "outputs": f"{task_description} | Modules: {teaching_modules_str}",
                "what_to_do": _what_to_do("KPA1", task_title, task_description),
                "evidence_required": _evidence_required(
                    "KPA1",
                    ["lecture", "assessment", "efundi", "lms", "class", "tutorial", "marks"],
                    f"{task_description} | Modules: {teaching_modules_str}",
                ),
            })
            task_counter += 1
        
        # Critical milestones
        tasks.append({
            "id": f"task_{task_counter:03d}",
            "kpa_code": "KPA1",
            "kpa_name": "Teaching and Learning",
            "title": f"Semester 1 marks submission deadline - {teaching_modules_str}",
            "cadence": "critical_milestone",
            "months": [6],
            "minimum_count": 1,
            "stretch_count": 1,
            "evidence_hints": ["marks", "gradebook", "submission", "assessment", "semester 1", teaching_modules_str],
            "outputs": f"Semester 1 assessment completion for {teaching_modules_str}",
            "what_to_do": _what_to_do("KPA1", f"Semester 1 marks submission deadline - {teaching_modules_str}", ""),
            "evidence_required": _evidence_required(
                "KPA1",
                ["marks", "gradebook", "submission", "assessment", "semester 1"],
                f"Semester 1 assessment completion for {teaching_modules_str}",
            ),
        })
        task_counter += 1
        
        tasks.append({
            "id": f"task_{task_counter:03d}",
            "kpa_code": "KPA1",
            "kpa_name": "Teaching and Learning",
            "title": f"Year-end marks and moderation - {teaching_modules_str}",
            "cadence": "critical_milestone",
            "months": [12],
            "minimum_count": 1,
            "stretch_count": 1,
            "evidence_hints": ["moderation", "marks", "exam", "final", "year-end", teaching_modules_str],
            "outputs": f"Year-end assessment completion and moderation for {teaching_modules_str}",
            "what_to_do": _what_to_do("KPA1", f"Year-end marks and moderation - {teaching_modules_str}", ""),
            "evidence_required": _evidence_required(
                "KPA1",
                ["moderation", "marks", "exam", "final", "year-end"],
                f"Year-end assessment completion and moderation for {teaching_modules_str}",
            ),
        })
        task_counter += 1
        
        # Module-specific tasks
        tasks.append({
            "id": f"task_{task_counter:03d}",
            "kpa_code": "KPA1",
            "kpa_name": "Teaching and Learning",
            "title": f"Module quality assurance - {teaching_modules_str}",
            "cadence": "semester",
            "months": [6, 12],
            "minimum_count": 2,
            "stretch_count": 4,
            "evidence_hints": ["moderation", "peer review", "quality", "evaluation", teaching_modules_str],
            "outputs": f"Module evaluation and improvement for {teaching_modules_str}",
            "what_to_do": _what_to_do("KPA1", f"Module quality assurance - {teaching_modules_str}", ""),
            "evidence_required": _evidence_required(
                "KPA1",
                ["moderation", "peer review", "quality", "evaluation"],
                f"Module evaluation and improvement for {teaching_modules_str}",
            ),
        })
        task_counter += 1
    
    # KPA2: OHS (quarterly)
    for month in [2, 5, 8, 11]:
        tasks.append({
            "id": f"task_{task_counter:03d}",
            "kpa_code": "KPA2",
            "kpa_name": "Occupational Health & Safety",
            "title": "OHS compliance check",
            "cadence": "quarterly",
            "months": [month],
            "minimum_count": 1,
            "stretch_count": 1,
            "evidence_hints": ["ohs", "safety", "compliance", "training", "popia", "dalro"],
            "outputs": "; ".join(ohs[:2]) if ohs else "OHS compliance activities",
            "what_to_do": _what_to_do("KPA2", "OHS compliance check", ""),
            "evidence_required": _evidence_required(
                "KPA2",
                ["ohs", "safety", "compliance", "training", "popia", "dalro"],
                "; ".join(ohs[:2]) if ohs else "OHS compliance activities",
            ),
        })
        task_counter += 1
    
    # KPA3: Research (NWU Research Calendar aligned)
    kpa3_hours = kpa_summary.get("KPA3", {}).get("hours", 0.0)
    if kpa3_hours > 0:
        research_calendar = {
            1: "Research planning & ethics applications",
            2: "Data collection / Literature review",
            3: "NRF rating window / Grant applications",
            4: "Conference submission deadlines",
            5: "Mid-year research review preparation",
            6: "Mid-year research output submission",
            7: "Winter research focus period",
            8: "Manuscript drafting & revisions",
            9: "Conference presentations",
            10: "Year-end publication push",
            11: "NWU Research Awards submissions",
            12: "Annual research reporting"
        }
        
        for month in range(1, 13):
            focus_area = research_calendar.get(month, "Research progress")
            
            tasks.append({
                "id": f"task_{task_counter:03d}",
                "kpa_code": "KPA3",
                "kpa_name": "Research, Innovation & Creative Outputs",
                "title": f"{focus_area}",
                "cadence": "monthly",
                "months": [month],
                "minimum_count": 2 if month in [3,6,9,11] else 1,  # Higher expectations in key months
                "stretch_count": 4 if month in [3,6,9,11] else 3,
                "evidence_hints": ["draft", "manuscript", "ethics", "grant", "submission", "review", "publication", "conference", "nrf"],
                "outputs": f"{focus_area} | " + ("; ".join(research[:2]) if research else "Research activities as per TA"),
                "what_to_do": _what_to_do("KPA3", focus_area, ""),
                "evidence_required": _evidence_required(
                    "KPA3",
                    ["draft", "manuscript", "ethics", "grant", "submission", "review", "publication", "conference", "nrf"],
                    f"{focus_area} | " + ("; ".join(research[:2]) if research else "Research activities as per TA"),
                ),
            })
            task_counter += 1
        
        # Critical research milestones
        tasks.append({
            "id": f"task_{task_counter:03d}",
            "kpa_code": "KPA3",
            "kpa_name": "Research, Innovation & Creative Outputs",
            "title": "NRF grant application / Rating submission",
            "cadence": "critical_milestone",
            "months": [3],
            "minimum_count": 1,
            "stretch_count": 2,
            "evidence_hints": ["nrf", "grant", "rating", "application", "submission"],
            "outputs": "NRF funding application or rating improvement",
            "what_to_do": _what_to_do("KPA3", "NRF grant application / Rating submission", ""),
            "evidence_required": _evidence_required(
                "KPA3",
                ["nrf", "grant", "rating", "application", "submission"],
                "NRF funding application or rating improvement",
            ),
        })
        task_counter += 1
        
        tasks.append({
            "id": f"task_{task_counter:03d}",
            "kpa_code": "KPA3",
            "kpa_name": "Research, Innovation & Creative Outputs",
            "title": "Mid-year research output (publication/conference)",
            "cadence": "critical_milestone",
            "months": [6],
            "minimum_count": 1,
            "stretch_count": 2,
            "evidence_hints": ["publication", "conference", "acceptance", "submission", "doi"],
            "outputs": "Research publication submission or conference acceptance",
            "what_to_do": _what_to_do("KPA3", "Mid-year research output (publication/conference)", ""),
            "evidence_required": _evidence_required(
                "KPA3",
                ["publication", "conference", "acceptance", "submission", "doi"],
                "Research publication submission or conference acceptance",
            ),
        })
        task_counter += 1
        
        tasks.append({
            "id": f"task_{task_counter:03d}",
            "kpa_code": "KPA3",
            "kpa_name": "Research, Innovation & Creative Outputs",
            "title": "Year-end research output (accredited publication)",
            "cadence": "critical_milestone",
            "months": [11],
            "minimum_count": 1,
            "stretch_count": 2,
            "evidence_hints": ["publication", "accepted", "doi", "journal", "accredited", "subsidy"],
            "outputs": "Accredited research publication for subsidy purposes",
            "what_to_do": _what_to_do("KPA3", "Year-end research output (accredited publication)", ""),
            "evidence_required": _evidence_required(
                "KPA3",
                ["publication", "accepted", "doi", "journal", "accredited", "subsidy"],
                "Accredited research publication for subsidy purposes",
            ),
        })
        task_counter += 1
        
        # Supervision tasks if applicable
        tasks.append({
            "id": f"task_{task_counter:03d}",
            "kpa_code": "KPA3",
            "kpa_name": "Research, Innovation & Creative Outputs",
            "title": "Postgraduate supervision meetings & progress tracking",
            "cadence": "semester",
            "months": [3, 6, 9, 12],
            "minimum_count": 4,
            "stretch_count": 8,
            "evidence_hints": ["supervision", "postgraduate", "masters", "phd", "meeting", "progress report"],
            "outputs": "Postgraduate student supervision and progress monitoring",
            "what_to_do": _what_to_do("KPA3", "Postgraduate supervision meetings & progress tracking", ""),
            "evidence_required": _evidence_required(
                "KPA3",
                ["supervision", "postgraduate", "masters", "phd", "meeting", "progress report"],
                "Postgraduate student supervision and progress monitoring",
            ),
        })
        task_counter += 1
    
    # KPA4: Academic Leadership & Administration (NWU governance cycle aligned)
    kpa4_hours = kpa_summary.get("KPA4", {}).get("hours", 0.0)
    if kpa4_hours > 0:
        leadership_calendar = {
            1: "Annual planning & goal setting",
            2: "Faculty board meetings / School committees",
            3: "Budget planning & resource allocation",
            4: "Student complaint resolutions / Quality assurance",
            5: "Mid-year performance reviews (staff)",
            6: "Senate meetings / Academic planning",
            7: "Strategic planning sessions",
            8: "Curriculum review & accreditation prep",
            9: "Faculty board meetings / Programme evaluations",
            10: "Budget reviews & resource reallocation",
            11: "Year-end performance assessments",
            12: "Annual reporting & strategic reviews"
        }
        
        for month in range(1, 13):
            focus_area = leadership_calendar.get(month, "Leadership activities")
            
            tasks.append({
                "id": f"task_{task_counter:03d}",
                "kpa_code": "KPA4",
                "kpa_name": "Academic Leadership & Administration",
                "title": f"{focus_area}",
                "cadence": "monthly",
                "months": [month],
                "minimum_count": 2 if month in [3,6,9,12] else 1,  # Higher expectations in key governance months
                "stretch_count": 4 if month in [3,6,9,12] else 2,
                "evidence_hints": ["meeting", "minutes", "committee", "chair", "agenda", "administration", "senate", "faculty board"],
                "outputs": f"{focus_area} | " + ("; ".join(leadership[:2]) if leadership else "Leadership activities as per TA"),
                "what_to_do": _what_to_do("KPA4", focus_area, ""),
                "evidence_required": _evidence_required(
                    "KPA4",
                    ["meeting", "minutes", "committee", "chair", "agenda", "administration", "senate", "faculty board"],
                    f"{focus_area} | " + ("; ".join(leadership[:2]) if leadership else "Leadership activities as per TA"),
                ),
            })
            task_counter += 1
        
        # Critical leadership milestones
        tasks.append({
            "id": f"task_{task_counter:03d}",
            "kpa_code": "KPA4",
            "kpa_name": "Academic Leadership & Administration",
            "title": "Mid-year performance reviews & staff development",
            "cadence": "critical_milestone",
            "months": [5],
            "minimum_count": 1,
            "stretch_count": 1,
            "evidence_hints": ["performance review", "mid-year", "staff development", "mentoring"],
            "outputs": "Staff performance reviews and development planning",
            "what_to_do": _what_to_do("KPA4", "Mid-year performance reviews & staff development", ""),
            "evidence_required": _evidence_required(
                "KPA4",
                ["performance review", "mid-year", "staff development", "mentoring"],
                "Staff performance reviews and development planning",
            ),
        })
        task_counter += 1
        
        tasks.append({
            "id": f"task_{task_counter:03d}",
            "kpa_code": "KPA4",
            "kpa_name": "Academic Leadership & Administration",
            "title": "Programme accreditation & quality assurance",
            "cadence": "semester",
            "months": [4, 10],
            "minimum_count": 2,
            "stretch_count": 4,
            "evidence_hints": ["accreditation", "quality assurance", "programme review", "heqc", "cheps"],
            "outputs": "Programme accreditation documentation and quality reviews",
            "what_to_do": _what_to_do("KPA4", "Programme accreditation & quality assurance", ""),
            "evidence_required": _evidence_required(
                "KPA4",
                ["accreditation", "quality assurance", "programme review", "heqc", "cheps"],
                "Programme accreditation documentation and quality reviews",
            ),
        })
        task_counter += 1
    
    # KPA5: Social Responsiveness (quarterly)
    kpa5_hours = kpa_summary.get("KPA5", {}).get("hours", 0.0)
    if kpa5_hours > 0:
        for month in [3, 6, 9, 12]:
            tasks.append({
                "id": f"task_{task_counter:03d}",
                "kpa_code": "KPA5",
                "kpa_name": "Social Responsiveness",
                "title": "Community engagement / industry involvement",
                "cadence": "quarterly",
                "months": [month],
                "minimum_count": 1,
                "stretch_count": 2,
                "evidence_hints": ["community", "engagement", "outreach", "school", "workshop", "industry"],
                "outputs": "; ".join(social[:2]) if social else "Community engagement activities",
                "what_to_do": _what_to_do("KPA5", "Community engagement / industry involvement", ""),
                "evidence_required": _evidence_required(
                    "KPA5",
                    ["community", "engagement", "outreach", "school", "workshop", "industry"],
                    "; ".join(social[:2]) if social else "Community engagement activities",
                ),
            })
            task_counter += 1
    
    # Build lead/lag indicators per KPA
    lead_lag = {
        "KPA1": {"lead": "Teaching delivery", "lag": "Assessment completion"},
        "KPA2": {"lead": "Training completion", "lag": "Compliance verification"},
        "KPA3": {"lead": "Research activities", "lag": "Publications/outputs"},
        "KPA4": {"lead": "Meeting attendance", "lag": "Administrative deliverables"},
        "KPA5": {"lead": "Engagement activities", "lag": "Impact reports"}
    }
    
    # Build by_month structure for UI
    by_month: Dict[str, List[Dict[str, Any]]] = {}
    for month in range(1, 13):
        month_key = f"{year}-{month:02d}"
        by_month[month_key] = [t for t in tasks if month in t.get("months", [])]
    
    return {
        "ok": True,
        "staff_id": staff_id,
        "year": year,
        "kpa_summary": kpa_summary,
        "tasks": tasks,
        "by_month": by_month,
        "lead_lag": lead_lag,
        "task_count": len(tasks),
        "months": [f"{year}-{m:02d}" for m in range(1, 13)]
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
