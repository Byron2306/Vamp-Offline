"""
PA Report Generator - matches PA_20172672_2025_final.xlsx format exactly.

Generates Performance Agreement with:
- KPA Name
- Outputs (bulleted list from TA)
- KPIs (from kpi_taxonomy)
- Weight (%)
- Hours
- Outcomes (from outcomes_library)
- Active (Y/N)
"""

import json
from pathlib import Path
from typing import Any, Dict, List
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font

REPO_ROOT = Path(__file__).resolve().parents[2]

def _load_kpi_taxonomy() -> Dict[str, List[str]]:
    """Load detailed KPI taxonomy for each KPA."""
    # Use the detailed KPIs from batch10 generator
    return {
        "KPA1": [
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
        "KPA2": [
            "Completed OHS training/induction (mandatory NWU modules)",
            "Risk assessment documents for labs, fieldwork, and events",
            "Zero-incident reports for labs or teaching spaces",
            "Incident reporting records (if applicable)",
            "Participation in OHS committees or audits",
            "Evidence of student OHS induction",
            "Compliance with COVID-19 or pandemic protocols",
            "Use of NWU OHS tools (e.g., digital safety platforms)"
        ],
        "KPA3": [
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
        "KPA4": [
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
        "KPA5": [
            "Registered community engagement projects",
            "Service-learning initiatives in curriculum",
            "Public lectures or science engagement activities",
            "Signed MoUs with NGOs, schools, or local government",
            "Community-based research with impact reports",
            "Media participation (e.g., radio, TV, newspapers)",
            "Recognition or awards for societal impact",
            "Advisory board or committee service",
            "Volunteer work using academic expertise"
        ]
    }


def _load_outcomes_library() -> str:
    """Load and format outcomes from values_index.json."""
    path = REPO_ROOT / "backend" / "data" / "nwu_brain" / "values_index.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        values = [v["name"] for v in data.get("core_values", [])]
        return "; ".join(values)
    # Fallback to basic values
    return "Excellence; Ethics; Unity in Diversity; Human Dignity; Commitment; Self-Respect; Respect for Others; Accountability; Transparency; Innovation; Social Responsiveness; Collaboration; Lifelong Learning; Environmental Stewardship; Service Orientation"


def _bullet_list(items: List[str]) -> str:
    """Format list items with bullet points."""
    cleaned = [str(x).strip() for x in items if str(x).strip()]
    return "\n".join([f"• {x}" for x in cleaned])


def _extract_outputs_from_contract(contract_data: Dict[str, Any], kpa_code: str) -> List[str]:
    """Extract all outputs/tasks for a KPA from contract or expectations data."""
    outputs = []
    
    # First, try to extract from tasks array (expectations format)
    tasks = contract_data.get("tasks", [])
    if tasks and kpa_code == "KPA1":  # Special handling for Teaching
        # For teaching, provide general summary instead of detailed month-by-month tasks
        teaching_modules = set()
        has_supervision = False
        has_teaching_practice = False
        
        for task in tasks:
            if task.get("kpa_code") == kpa_code:
                # Extract module information
                task_outputs = task.get("outputs", "")
                if "Modules:" in task_outputs:
                    # Extract module codes from "Modules: CODE (students), CODE (students)" format
                    import re
                    # Match patterns like "HISE411 (85 students)" or "ERTP 671 (1 students)"
                    module_matches = re.findall(r'([A-Z0-9 ]+)\s*\(\d+\s+students?\)', task_outputs)
                    for match in module_matches:
                        teaching_modules.add(match.strip())
                
                # Check for supervision
                if "supervision" in task_outputs.lower():
                    has_supervision = True
                
                # Check for teaching practice
                if "teaching practice" in task_outputs.lower():
                    has_teaching_practice = True
        
        # Create general summary
        if teaching_modules:
            module_list = sorted(list(teaching_modules))
            outputs.append(f"Deliver curriculum for modules: {', '.join(module_list)}")
        
        outputs.append("Complete all assessment design, delivery, and moderation for assigned modules")
        outputs.append("Provide student support, feedback, and academic advising")
        outputs.append("Maintain LMS presence and engage students through eFundi")
        outputs.append("Participate in curriculum development and quality assurance")
        
        if has_supervision:
            outputs.append("Supervise honours/undergraduate research projects")
        
        if has_teaching_practice:
            outputs.append("Conduct teaching practice supervision and assessment")
        
        return outputs
    
    # For other KPAs, use the original logic
    if tasks:
        for task in tasks:
            if task.get("kpa_code") == kpa_code:
                # Get the outputs field directly if available
                task_outputs = task.get("outputs", "")
                if task_outputs and task_outputs not in outputs:
                    outputs.append(task_outputs)
        # If we found outputs from tasks, return them
        if outputs:
            return outputs
    
    # Also check kpa_summary for teaching modules (in expectations format)
    kpa_summary = contract_data.get("kpa_summary", {})
    kpa_info = kpa_summary.get(kpa_code, {})
    
    if kpa_code == "KPA1":  # Teaching and Learning
        # Provide general summation instead of month-by-month details
        modules = kpa_info.get("teaching_modules", [])
        if modules:
            module_summaries = []
            for mod in modules:
                if isinstance(mod, dict):
                    code = mod.get("code", "")
                    students = mod.get("students", 0)
                    module_summaries.append(f"{code} ({students} students)")
                else:
                    module_summaries.append(str(mod))
            
            if module_summaries:
                outputs.append(f"Deliver curriculum for modules: {', '.join(module_summaries)}")
        
        # General teaching responsibilities
        outputs.append("Complete all assessment design, delivery, and moderation for assigned modules")
        outputs.append("Provide student support, feedback, and academic advising")
        outputs.append("Maintain LMS presence and engage students through eFundi")
        outputs.append("Participate in curriculum development and quality assurance")
        
        # Supervision if applicable
        supervision = contract_data.get("supervision", [])
        if supervision:
            outputs.append("Supervise honours/undergraduate research projects")
        
        # Teaching practice if applicable
        if "teaching_practice" in str(contract_data).lower():
            outputs.append("Conduct teaching practice supervision and assessment")
    
    elif kpa_code == "KPA2":  # OHS
        ohs = contract_data.get("ohs", [])
        if isinstance(ohs, list) and ohs:
            outputs.extend(ohs)
        else:
            outputs.append("Compliance with institutional OHS requirements")
    
    elif kpa_code == "KPA3":  # Research
        research = contract_data.get("research", [])
        if isinstance(research, list):
            outputs.extend(research)
    
    elif kpa_code == "KPA4":  # Leadership
        leadership = contract_data.get("leadership", [])
        if isinstance(leadership, list):
            outputs.extend(leadership)
    
    elif kpa_code == "KPA5":  # Social Responsiveness
        social = contract_data.get("social", [])
        if isinstance(social, list):
            outputs.extend(social)
    
    return outputs


def generate_pa_report(contract_data: Dict[str, Any], staff_id: str, year: int) -> Dict[str, Any]:
    """
    Generate PA report data matching Excel format.
    
    Returns:
    {
        "rows": [
            {
                "kpa_name": "Teaching and Learning",
                "outputs": "• Module 1\n• Module 2",
                "kpis": "Curriculum delivery\nAssessment & feedback",
                "weight": 47.54,
                "hours": 792.99,
                "outcomes": "Excellence; Integrity; ...",
                "active": "Y"
            },
            ...
        ],
        "staff_id": str,
        "year": int
    }
    """
    kpa_summary = contract_data.get("kpa_summary", {})
    kpi_taxonomy = _load_kpi_taxonomy()
    outcomes_text = _load_outcomes_library()
    
    # KPA order matching Excel
    kpa_order = [
        ("KPA1", "Teaching and Learning"),
        ("KPA3", "Research and Innovation / Creative Outputs"),
        ("KPA5", "Social Responsiveness / Community and Industry Engagement"),
        ("KPA4", "Academic Leadership and Management"),
        ("KPA2", "Occupational Health and Safety")
    ]
    
    rows = []
    
    for kpa_code, default_name in kpa_order:
        kpa_info = kpa_summary.get(kpa_code, {})
        kpa_name = kpa_info.get("name", default_name)
        hours = kpa_info.get("hours", 0.0)
        weight = kpa_info.get("weight_pct", 0.0)
        
        # Extract outputs from contract
        outputs_list = _extract_outputs_from_contract(contract_data, kpa_code)
        outputs_text = _bullet_list(outputs_list) if outputs_list else ""
        
        # Get KPIs from taxonomy
        kpis_list = kpi_taxonomy.get(kpa_code, [])
        kpis_text = "\n".join(kpis_list) if kpis_list else ""  # Use all KPIs, not limited
        
        # OHS special case
        if kpa_code == "KPA2":
            if not outputs_text:
                outputs_text = "Compliance with institutional Occupational Health and Safety requirements"
            if not kpis_text:
                kpis_text = "Compliance with institutional Occupational Health and Safety requirements"
            if hours == 0:
                hours = 2.0
            if weight == 0:
                weight = 2.0
        
        rows.append({
            "kpa_code": kpa_code,
            "kpa_name": kpa_name,
            "outputs": outputs_text,
            "kpis": kpis_text,
            "weight": weight,
            "hours": hours,
            "outcomes": outcomes_text,
            "active": "Y"
        })
    
    return {
        "rows": rows,
        "staff_id": staff_id,
        "year": year,
        "title": f"Performance Agreement {staff_id} {year}"
    }


def export_pa_to_excel(pa_data: Dict[str, Any], output_path: Path) -> Path:
    """Export PA report data to Excel file matching the reference format."""
    wb = Workbook()
    ws = wb.active
    ws.title = "pa-report"
    
    # Title row
    ws.append([pa_data["title"], None, None, None, None, None, None])
    
    # Header row
    ws.append(["KPA Name", "Outputs", "KPIs", "Weight", "Hours", "Outcomes", "Active"])
    
    # Data rows
    for row in pa_data["rows"]:
        ws.append([
            row["kpa_name"],
            row["outputs"],
            row["kpis"],
            row["weight"],
            row["hours"],
            row["outcomes"],
            row["active"]
        ])
    
    # Formatting
    ws.column_dimensions["A"].width = 40
    ws.column_dimensions["B"].width = 50
    ws.column_dimensions["C"].width = 60
    ws.column_dimensions["D"].width = 10
    ws.column_dimensions["E"].width = 10
    ws.column_dimensions["F"].width = 40
    ws.column_dimensions["G"].width = 8
    
    # Wrap text for outputs, KPIs, outcomes
    wrap_alignment = Alignment(wrap_text=True, vertical="top")
    for row in ws.iter_rows(min_row=3, max_col=7):
        for cell in row:
            if cell.column_letter in {"B", "C", "F"}:
                cell.alignment = wrap_alignment
    
    # Bold headers
    bold_font = Font(bold=True)
    for cell in ws[1]:
        cell.font = bold_font
    for cell in ws[2]:
        cell.font = bold_font
    
    wb.save(output_path)
    return output_path
