from __future__ import annotations
import json
from pathlib import Path

def _load_json_vocab(path: str):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

# Load mapping vocabularies
vocab_dir = Path(__file__).parent.parent
KPI_TAXONOMY = _load_json_vocab(str(vocab_dir / 'kpi_taxonomy_nwu_education.json')) or {}
OUTCOMES_LIBRARY = _load_json_vocab(str(vocab_dir / 'outcomes_library.json')) or []
VALUES_INDEX = _load_json_vocab(str(vocab_dir / 'values_index.json')) or {}

# Extract detailed KPIs from KPA guidelines
KPA_DETAILED_KPI_MAP = {
    "Teaching and Learning, including Higher Degree Supervision": [
        "STLES results (Student Teaching and Learning Evaluation Surveys)",
        "Peer reviews of teaching (e.g., observation reports)",
        "eFundi LMS activity reports",
        "Teaching portfolios, including reflective narratives",
        "Pass and throughput rates for modules taught",
        "Curriculum development (e.g., new modules, curriculum renewal)",
        "Contact hours and module credits",
        "Teaching awards (e.g., Institutional Teaching Excellence Award - ITEA)",
        "Assessment and moderation compliance (aligned with NWU's policy)",
        "Supervision of undergraduate and honours students",
        "Use of innovative pedagogy, such as blended or AI-assisted learning"
    ],
    "Personal Research, Innovation and/or Creative Outputs": [
        "DHET-accredited journal articles (with ISSN/DOI)",
        "Conference papers (national or international)",
        "Books or book chapters (accredited)",
        "NRF rating status (e.g., Y1, C2)",
        "Research funding/grants (applications and awards)",
        "Research supervision (Master's and PhD graduations)",
        "Ethics approval letters (REC/HREC)",
        "Innovation outputs (e.g., patents, software, creative works)",
        "Research awards or commendations",
        "Editorial board membership or invited keynote talks"
    ],
    "Academic Leadership, Management and Administration": [
        "Head of Department, Program Leader, or Entity Director roles",
        "Faculty or institutional committee membership",
        "Mentorship of junior academics or tutors",
        "Accreditation or re-accreditation reports led",
        "Strategic planning or policy input",
        "Development and management of academic programs",
        "Performance management of reporting staff",
        "Leadership in transformation or equity initiatives",
        "Meeting minutes or official project documentation"
    ],
    "Social Responsiveness and Industry Involvement": [
        "Registered community engagement projects",
        "Service-learning initiatives in curriculum",
        "Public lectures or science engagement activities",
        "Signed MoUs with NGOs, schools, or local government",
        "Community-based research with impact reports",
        "Media participation (e.g., radio, TV, newspapers)",
        "Recognition or awards for societal impact",
        "Advisory board or committee service",
        "Volunteer work using academic expertise"
    ],
    "OHS (Occupational Health and Safety)": [
        "Completed OHS training/induction (mandatory NWU modules)",
        "Risk assessment documents for labs, fieldwork, and events",
        "Zero-incident reports for labs or teaching spaces",
        "Incident reporting records (if applicable)",
        "Participation in OHS committees or audits",
        "Evidence of student OHS induction",
        "Compliance with COVID-19 or pandemic protocols",
        "Use of NWU OHS tools (e.g., digital safety platforms)"
    ],
}

# Use detailed KPIs
KPA_KPI_MAP = KPA_DETAILED_KPI_MAP

# Use all core values for outcomes
all_values = [v["name"] for v in VALUES_INDEX.get("core_values", [])] if VALUES_INDEX else ["Excellence", "Innovation", "Integrity", "Social Responsiveness"]
KPA_OUTCOME_MAP = {kpa: "; ".join(all_values) for kpa in KPA_KPI_MAP.keys()}





from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font

from backend.batch8_aggregator import FinalPerformance, KPASummary
from backend.contracts.contract_builder import MergedKPA, PerformanceContract


KPA_ORDER: List[str] = [
    "Personal Research, Innovation and/or Creative Outputs",
    "Teaching and Learning, including Higher Degree Supervision",
    "Academic Leadership, Management and Administration",
    "Social Responsiveness and Industry Involvement",
    "OHS (Occupational Health and Safety)",
    "People Management",
]

HEADERS: List[str] = ["KPA Name", "KPA Description", "Outputs", "KPIs", "Weight", "Hours", "Outcomes", "Active"]

DEFAULT_PLACEHOLDER = "Not Available"


@dataclass
class Batch10Metadata:
    staff_no: str
    full_name: str
    year: int
    faculty: str
    post_level: str


@dataclass
class Batch10Results:
    kpa_summaries: Sequence[KPASummary]
    final_performance: FinalPerformance


@dataclass
class Batch10Input:
    contract: PerformanceContract
    batch8_results: Batch10Results
    metadata: Batch10Metadata


def _normalise_key(name: str) -> str:
    return " ".join(name.lower().split())


def _kpa_lookup(contract: PerformanceContract) -> Dict[str, MergedKPA]:
    lookup: Dict[str, MergedKPA] = {}
    for kpa in contract.kpas.values():
        lookup[_normalise_key(kpa.name)] = kpa
    return lookup


def _render_outputs(kpa_name: str, raw_outputs: object) -> str:
    # For Teaching & Learning, summarize as bullet list of key tasks
    if "teaching" in kpa_name.lower():
        mapped = KPA_KPI_MAP.get(kpa_name, [])
        if mapped:
            return "\n".join(f"• {kpi}" for kpi in mapped)
        return "Complete all module planning, assessment design, lesson delivery, and evidence upload for each assigned module."
    # For other KPAs, fallback to original logic
    if raw_outputs is None:
        return ""
    if isinstance(raw_outputs, str):
        return raw_outputs.strip()
    if isinstance(raw_outputs, Iterable):
        parts = [str(item).strip() for item in raw_outputs if str(item).strip()]
        return "\n".join(parts)
    return str(raw_outputs).strip()


def _extract_kpi_fields(raw: object) -> Optional[Dict[str, str]]:
    if raw is None:
        return None
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        return {"text": text, "measure": DEFAULT_PLACEHOLDER, "target": DEFAULT_PLACEHOLDER}

    if isinstance(raw, dict):
        text = str(
            raw.get("description")
            or raw.get("text")
            or raw.get("kpi")
            or raw.get("kpi_text")
            or ""
        ).strip()
        if not text:
            return None
        measure = str(raw.get("measure", "")).strip() or DEFAULT_PLACEHOLDER
        target = str(raw.get("target", "")).strip() or DEFAULT_PLACEHOLDER
        return {"text": text, "measure": measure, "target": target}

    return {"text": str(raw).strip(), "measure": DEFAULT_PLACEHOLDER, "target": DEFAULT_PLACEHOLDER}


def _render_kpis(kpa_name: str, raw_kpis: object) -> str:
    # Use mapped KPIs if available
    mapped = KPA_KPI_MAP.get(kpa_name, [])
    if mapped:
        return "\n".join(f"• {kpi}" for kpi in mapped)
    # Fallback to original logic
    if raw_kpis is None:
        return ""
    items: List[Dict[str, str]] = []
    if isinstance(raw_kpis, str):
        maybe = _extract_kpi_fields(raw_kpis)
        if maybe:
            items.append(maybe)
    elif isinstance(raw_kpis, dict):
        maybe = _extract_kpi_fields(raw_kpis)
        if maybe:
            items.append(maybe)
    elif isinstance(raw_kpis, Iterable):
        for entry in raw_kpis:
            maybe = _extract_kpi_fields(entry)
            if maybe:
                items.append(maybe)
    else:
        maybe = _extract_kpi_fields(raw_kpis)
        if maybe:
            items.append(maybe)

    blocks: List[str] = []
    for item in items:
        text = item.get("text", "").strip()
        if not text:
            continue
        measure = item.get("measure", DEFAULT_PLACEHOLDER) or DEFAULT_PLACEHOLDER
        target = item.get("target", DEFAULT_PLACEHOLDER) or DEFAULT_PLACEHOLDER
        block = f"• {text}\n  Measure: {measure}\n  Target: {target}"
        blocks.append(block)

    return "\n\n".join(blocks)


def _render_outcomes(kpa_name: str, raw_outcomes: object) -> str:
    mapped = KPA_OUTCOME_MAP.get(kpa_name)
    if mapped:
        return mapped
    # Fallback to original logic
    if raw_outcomes is None:
        return "To be evaluated at year-end"
    if isinstance(raw_outcomes, str):
        return raw_outcomes.strip() or "To be evaluated at year-end"
    if isinstance(raw_outcomes, Iterable):
        parts = [str(item).strip() for item in raw_outcomes if str(item).strip()]
        if parts:
            return "\n".join(parts)
        return "To be evaluated at year-end"
    return str(raw_outcomes).strip() or "To be evaluated at year-end"


def _render_description(raw_desc: object) -> str:
    if raw_desc is None:
        return DEFAULT_PLACEHOLDER
    if isinstance(raw_desc, str):
        return raw_desc.strip() or DEFAULT_PLACEHOLDER
    if isinstance(raw_desc, dict):
        # common keys we might find
        text = raw_desc.get("description") or raw_desc.get("text") or raw_desc.get("kpa_description")
        return str(text).strip() if text else DEFAULT_PLACEHOLDER
    if isinstance(raw_desc, Iterable):
        parts = [str(item).strip() for item in raw_desc if str(item).strip()]
        return "\n".join(parts) if parts else DEFAULT_PLACEHOLDER
    return str(raw_desc).strip() or DEFAULT_PLACEHOLDER


def _validate_rows(rows: List[List[object]]) -> None:
    if len(rows) < len(KPA_ORDER):
        raise ValueError("PA export aborted: missing KPA rows")

    weight_total = 0.0
    for row in rows:
        try:
            # weight is now at index 4 after adding KPA Description column
            weight_total += float(row[4] or 0)
        except Exception:
            continue

    if abs(weight_total - 100.0) > 0.5:
        raise ValueError("PA export aborted: weights do not sum to ~100%")


def _apply_layout(ws) -> None:
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 50
    ws.column_dimensions["C"].width = 45
    ws.column_dimensions["D"].width = 45
    ws.column_dimensions["E"].width = 10
    ws.column_dimensions["F"].width = 10
    ws.column_dimensions["G"].width = 40
    ws.column_dimensions["H"].width = 8

    wrap_alignment = Alignment(wrap_text=True, vertical="top")
    for row in ws.iter_rows(min_row=3, max_col=8):
        for cell in row:
            if cell.column_letter in {"B", "C", "D", "G"}:
                cell.alignment = wrap_alignment

    bold_font = Font(bold=True)
    for cell in ws[1]:
        cell.font = bold_font
    for cell in ws[2]:
        cell.font = bold_font


def generate_pa_report(batch10_input: Batch10Input, output_dir: Path) -> Path:
    contract = batch10_input.contract
    metadata = batch10_input.metadata
    lookup = _kpa_lookup(contract)

    rows: List[List[object]] = []
    for kpa_name in KPA_ORDER:
        kpa_key = _normalise_key(kpa_name)
        kpa = lookup.get(kpa_key)

        description = _render_description(getattr(kpa, "context", {}) if kpa else None)
        outputs = _render_outputs(kpa_name, kpa.outputs if kpa else None)
        kpis = _render_kpis(kpa_name, kpa.kpis if kpa else None)
        weight = float(kpa.weight_pct) if kpa else 0.0
        hours = float(kpa.hours) if kpa else 0.0
        outcomes = _render_outcomes(kpa_name, kpa.outcomes if kpa else None)
        active_flag = "Y" if (kpa.active if kpa else True) else "N"

        rows.append([kpa_name, description, outputs, kpis, weight, hours, outcomes, active_flag])

    _validate_rows(rows)

    wb = Workbook()
    ws = wb.active
    ws.title = "pa-report"

    title_cell = ws.cell(row=1, column=1)
    title_cell.value = f"Performance Agreement {metadata.staff_no} {metadata.year}"
    title_cell.font = Font(bold=True)

    ws.append(HEADERS)
    for row in rows:
        ws.append(row)

    _apply_layout(ws)

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"PA_{metadata.staff_no}_{metadata.year}.xlsx"
    wb.save(out_path)
    return out_path

