from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).resolve().parent / "data"
WORK_CONTEXT_DIR = DATA_DIR / "work_context"
WORK_CONTEXT_DIR.mkdir(parents=True, exist_ok=True)

MONTH_NAMES = {
    1: "January",
    2: "February",
    3: "March",
    4: "April",
    5: "May",
    6: "June",
    7: "July",
    8: "August",
    9: "September",
    10: "October",
    11: "November",
    12: "December",
}
INTERVIEW_SCHEMA_VERSION = 2

OHS_EVIDENCE_SCOPE = [
    "formal OHS/safety training",
    "campus access or entry compliance",
    "security instructions or incidents",
    "wellness and employee wellbeing activities",
    "risk assessment or hazard reporting",
    "POPIA/DALRO/compliance notices",
    "evacuation, emergency, or building-safety notices",
]


def context_path(staff_id: str, year: int) -> Path:
    safe_id = str(staff_id).replace("/", "-").replace("\\", "-")
    return WORK_CONTEXT_DIR / f"work_context_{safe_id}_{int(year)}.json"


def load_work_context(staff_id: str, year: int) -> dict[str, Any]:
    path = context_path(staff_id, year)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def save_work_context(staff_id: str, year: int, payload: dict[str, Any]) -> dict[str, Any]:
    context = dict(payload or {})
    context["staff_id"] = str(staff_id)
    context["year"] = int(year)
    path = context_path(staff_id, year)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(context, indent=2, ensure_ascii=False), encoding="utf-8")
    return context


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _month_list(value: Any) -> list[int]:
    if isinstance(value, list):
        raw = value
    elif value in (None, ""):
        return []
    else:
        raw = [value]
    months: list[int] = []
    for item in raw:
        try:
            month = int(item)
        except Exception:
            continue
        if 1 <= month <= 12 and month not in months:
            months.append(month)
    return months


def _months_from_names(values: list[Any]) -> list[int]:
    tokens = " ".join(str(v or "") for v in values).lower()
    months: list[int] = []
    aliases = {
        "jan": 1,
        "january": 1,
        "feb": 2,
        "february": 2,
        "mar": 3,
        "march": 3,
        "apr": 4,
        "april": 4,
        "may": 5,
        "jun": 6,
        "june": 6,
        "jul": 7,
        "july": 7,
        "aug": 8,
        "august": 8,
        "sep": 9,
        "sept": 9,
        "september": 9,
        "oct": 10,
        "october": 10,
        "nov": 11,
        "november": 11,
        "dec": 12,
        "december": 12,
    }
    for word in re.findall(r"[a-z]+", tokens):
        month = aliases.get(word)
        if month and month not in months:
            months.append(month)
    return months


def _is_answered(value: Any) -> bool:
    if value in (None, "", [], {}):
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return True


def _project_aliases(name: str) -> list[str]:
    lower = name.lower()
    aliases: list[str] = [name]
    if "citesaga" in lower or "cite saga" in lower:
        aliases += ["Citesaga", "CiteSaga", "cite saga", "citation game", "AOSIS", "InfoEd"]
    if "workready" in lower or "work ready" in lower or "work-read" in lower:
        aliases += ["WorkReady", "work ready", "work-readiness", "work readiness"]
    if "gbl" in lower or "game" in lower or "ai" in lower:
        aliases += [
            "AI GBL",
            "AI and GBL",
            "game-based learning",
            "game based learning",
            "gamification",
            "gamified learning",
            "play-based learning",
            "playful learning",
            "serious games",
            "VAMP",
            "SERAPH",
            "agentic AI",
            "AI system",
            "software prototype",
            "invention disclosure",
            "technology disclosure",
            "IP disclosure",
            "D2026",
            "D2026-164",
            "tech transfer",
        ]
    seen: set[str] = set()
    result: list[str] = []
    for alias in aliases:
        alias = _norm(alias)
        key = alias.lower()
        if alias and key not in seen:
            seen.add(key)
            result.append(alias)
    return result


def draft_work_context_from_ta(staff_id: str, year: int, ta_summary: dict[str, Any]) -> dict[str, Any]:
    """Create a draft context from TA extraction; staff can edit/confirm it."""
    projects: list[dict[str, Any]] = []
    publications: list[dict[str, Any]] = []
    committees: list[dict[str, Any]] = []

    for item in ta_summary.get("research") or []:
        text = _norm(item)
        lower = text.lower()
        if not text:
            continue
        if "book" in lower or "article" in lower or "chapter" in lower or "publication" in lower:
            publications.append(
                {
                    "name": text.split(",")[0][:80],
                    "aliases": _project_aliases(text),
                    "active_months": [],
                    "phase_by_month": {},
                    "status": "needs_clarification",
                    "evidence_types": ["draft", "submission", "review", "acceptance", "publication correspondence"],
                    "source": "ta_draft",
                }
            )
        elif "project" in lower or any(marker in lower for marker in ("learning", "education", "knowledge", "oep", "gbl", "workready", "citesaga")):
            projects.append(
                {
                    "name": text.split(":")[0][:80],
                    "aliases": _project_aliases(text),
                    "active_months": [],
                    "phase_by_month": {},
                    "status": "needs_clarification",
                    "collaborators": [],
                    "evidence_types": ["planning email", "ethics", "intervention status", "draft", "submission", "prototype", "disclosure"],
                    "source": "ta_draft",
                }
            )

    for item in ta_summary.get("leadership") or []:
        text = _norm(item)
        if text:
            committees.append(
                {
                    "name": text.split(":")[0][:80],
                    "aliases": [text.split(":")[0].strip()],
                    "active_months": [],
                    "status": "needs_clarification",
                    "evidence_types": ["calendar attendance", "agenda", "minutes", "action email"],
                    "source": "ta_draft",
                }
            )

    context = {
        "staff_id": str(staff_id),
        "year": int(year),
        "status": "draft",
        "interview_schema_version": INTERVIEW_SCHEMA_VERSION,
        "projects": projects,
        "publications": publications,
        "committees": committees,
        "supervision": {
            "active_months": [],
            "students": ta_summary.get("supervision") or [],
            "status": "needs_clarification" if ta_summary.get("supervision") else "not_in_ta",
            "evidence_types": ["calendar attendance", "supervision email", "progress note", "proposal/dissertation feedback"],
        },
        "interview_notes": [],
    }
    return ensure_work_context_schema(context, ta_summary)


def ensure_work_context_schema(context: dict[str, Any], ta_summary: dict[str, Any] | None = None) -> dict[str, Any]:
    """Add newer interview fields to an existing saved context without deleting staff edits."""
    ta_summary = ta_summary or {}
    context = dict(context or {})
    context["interview_schema_version"] = INTERVIEW_SCHEMA_VERSION

    teaching_modules = ta_summary.get("teaching_modules") or []
    teaching_months = sorted({1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12})
    teaching = dict(context.get("teaching_learning") or {})
    teaching.setdefault("status", "fixed_calendar")
    teaching.setdefault("active_months", teaching_months)
    teaching.setdefault("modules", teaching_modules)
    teaching.setdefault(
        "evidence_types",
        [
            "eFundi setup/resources/announcements",
            "assessment briefs/rubrics/gradebook exports",
            "moderation and marks evidence",
            "lectures, lesson plans, study guides, reading lists",
        ],
    )
    teaching.setdefault("needs_exception_review", True)
    context["teaching_learning"] = teaching

    tp_windows = ta_summary.get("teaching_practice_windows") or []
    tp_months = _months_from_names(tp_windows)
    community = dict(context.get("community_engagement") or {})
    community.setdefault("status", "static_windows")
    community.setdefault("teaching_practice_windows", tp_windows)
    community.setdefault("active_months", tp_months or [4, 7])
    community.setdefault(
        "aliases",
        [
            "TPRAC",
            "teaching practice",
            "WIL",
            "work integrated learning",
            "school visit",
            "community engagement",
            "social responsiveness",
            "service learning",
            "volunteer work",
            "public engagement",
            "industry engagement",
            "industry partner",
            "commercialisation",
            "commercialization",
            "technology transfer",
            "tech transfer",
            "TTIS",
            "Hannes Malan",
            "invention disclosure",
            "technology disclosure",
            "IP disclosure",
            "disclosure",
        ],
    )
    community.setdefault(
        "evidence_types",
        [
            "calendar visit",
            "assessment form",
            "school placement correspondence",
            "student teacher feedback",
            "commercialisation correspondence",
            "industry meeting",
            "technology transfer email",
            "disclosure document",
            "service-learning artefact",
            "volunteer or outreach evidence",
        ],
    )
    community.setdefault(
        "scope_options",
        [
            "WIL/TPRAC/teaching practice",
            "service learning",
            "volunteer work",
            "community outreach/public engagement",
            "industry partnerships",
            "commercialisation/technology transfer",
            "invention/IP/technology disclosures",
        ],
    )
    context["community_engagement"] = community

    ohs = dict(context.get("ohs") or {})
    ohs.setdefault("status", "broad_compliance_context")
    ohs.setdefault("active_months", list(range(1, 13)))
    ohs.setdefault("aliases", ["OHS", "occupational health", "safety", "compliance", "security", "wellness"])
    ohs.setdefault("evidence_scope", OHS_EVIDENCE_SCOPE)
    ohs.setdefault("needs_scope_review", True)
    context["ohs"] = ohs

    admin = dict(context.get("administration") or {})
    admin.setdefault("status", "mostly_fixed_committee_calendar")
    admin.setdefault("evidence_types", ["calendar attendance", "agenda", "minutes", "action email", "committee pack"])
    admin.setdefault("needs_exception_review", True)
    context["administration"] = admin

    for project in context.get("projects") or []:
        if not isinstance(project, dict):
            continue
        project.setdefault("current_status", "")
        project.setdefault("completed_to_date", "")
        project.setdefault("next_milestones", "")
        project.setdefault("evidence_locations", "")
        project.setdefault("timeframe_confidence", "needs_staff_confirmation")

    for publication in context.get("publications") or []:
        if not isinstance(publication, dict):
            continue
        publication.setdefault("current_status", "")
        publication.setdefault("completed_to_date", "")
        publication.setdefault("target_venue_or_output", "")
        publication.setdefault("next_milestones", "")
        publication.setdefault("evidence_locations", "")
        publication.setdefault("timeframe_confidence", "needs_staff_confirmation")

    supervision = context.get("supervision") if isinstance(context.get("supervision"), dict) else {}
    supervision = dict(supervision)
    supervision.setdefault("active_months", [])
    if not _is_answered(supervision.get("students")) and _is_answered(ta_summary.get("supervision")):
        supervision["students"] = ta_summary.get("supervision") or []
    else:
        supervision.setdefault("students", ta_summary.get("supervision") or supervision.get("students") or [])
    supervision.setdefault("stage_by_student", "")
    supervision.setdefault("evidence_locations", "")
    supervision.setdefault(
        "stage_options",
        [
            "topic/proposal planning",
            "scientific committee submission",
            "ethics application",
            "ethics approved",
            "intervention/data collection",
            "analysis",
            "chapter feedback",
            "submission/examination",
        ],
    )
    supervision.setdefault(
        "evidence_types",
        ["meeting/calendar", "student email", "chapter/proposal feedback", "ethics/scientific committee correspondence"],
    )
    context["supervision"] = supervision

    return context


def interview_questions(context: dict[str, Any], max_questions: int = 40) -> list[dict[str, Any]]:
    """Return deterministic clarification prompts for the staff-context interview."""
    context = ensure_work_context_schema(context)
    questions: list[dict[str, Any]] = []

    teaching = context.get("teaching_learning") if isinstance(context.get("teaching_learning"), dict) else {}
    if teaching.get("needs_exception_review") and not _is_answered(teaching.get("exceptions_or_notes")):
        questions.append(
            {
                "id": "teaching_fixed_cycle_exceptions",
                "type": "teaching_exceptions",
                "target": "teaching_learning",
                "question": "Teaching and Learning follows fixed semester intervals. Are there any exceptions VAMP must know for modules, eFundi, assessments, moderation, or marks timing this year?",
            }
        )

    community = context.get("community_engagement") if isinstance(context.get("community_engagement"), dict) else {}
    if not _is_answered(community.get("confirmed_windows")):
        windows = ", ".join(str(w) for w in community.get("teaching_practice_windows") or []) or "April and July"
        questions.append(
            {
                "id": "community_tprac_windows",
                "type": "community_windows",
                "target": "community_engagement",
                "question": f"Community engagement may include static WIL/TPRAC windows, usually {windows}, but also service learning, volunteer work, industry engagement, commercialisation/tech transfer, and disclosures. Confirm exact months/days, which of these should count, and aliases such as TPRAC, WIL, Hannes Malan, tech transfer, commercialisation, disclosure, or school visits.",
            }
        )

    ohs = context.get("ohs") if isinstance(context.get("ohs"), dict) else {}
    if ohs.get("needs_scope_review") and not _is_answered(ohs.get("confirmed_scope")):
        questions.append(
            {
                "id": "ohs_scope",
                "type": "ohs_scope",
                "target": "ohs",
                "question": "OHS is broad. Which evidence should count for you this year: safety training, campus-entry compliance, security, wellness, POPIA/DALRO, risk notices, evacuation/building safety, or specific workshop days?",
            }
        )

    admin = context.get("administration") if isinstance(context.get("administration"), dict) else {}
    if admin.get("needs_exception_review") and not _is_answered(admin.get("fixed_calendar_notes")):
        questions.append(
            {
                "id": "admin_fixed_calendar",
                "type": "admin_calendar",
                "target": "administration",
                "question": "Administration/committee work is mostly fixed. Are there known meeting months, abbreviations, recurring days, or committees VAMP should include or exclude beyond SMC/SG/faculty/forum terms?",
            }
        )

    for project in context.get("projects") or []:
        name = project.get("name") or "research project"
        if not _month_list(project.get("active_months")):
            questions.append(
                {
                    "id": f"project_months::{name}",
                    "type": "months",
                    "target": "projects",
                    "name": name,
                    "question": f"Which months should VAMP expect evidence for {name}, and which months were only planning or waiting?",
                }
            )
        if not project.get("collaborators"):
            questions.append(
                {
                    "id": f"project_people::{name}",
                    "type": "people",
                    "target": "projects",
                    "name": name,
                    "question": f"Who are the collaborators, students, administrators, or approvers linked to {name}?",
                }
            )
        if not project.get("phase_by_month"):
            questions.append(
                {
                    "id": f"project_phases::{name}",
                    "type": "phase_by_month",
                    "target": "projects",
                    "name": name,
                    "question": f"What phase was {name} in by month: planning, ethics, data/intervention, writing, submission, review, accepted, or deferred?",
                }
            )
        if not _is_answered(project.get("current_status")):
            questions.append(
                {
                    "id": f"project_status::{name}",
                    "type": "current_status",
                    "target": "projects",
                    "name": name,
                    "question": f"What is the current status of {name}? Mention what had already happened, what was pending, and whether January-March evidence should be planning, ethics, intervention/data, prototype/disclosure, writing, or follow-up.",
                }
            )
        if not _is_answered(project.get("evidence_locations")):
            questions.append(
                {
                    "id": f"project_evidence_locations::{name}",
                    "type": "evidence_locations",
                    "target": "projects",
                    "name": name,
                    "question": f"Where is evidence for {name} likely to live: Outlook senders/subjects, calendar meetings, eFundi, local folders, disclosure systems, ethics systems, Teams, or documents?",
                }
            )

    for publication in context.get("publications") or []:
        name = publication.get("name") or "publication"
        if not _month_list(publication.get("active_months")):
            questions.append(
                {
                    "id": f"publication_months::{name}",
                    "type": "months",
                    "target": "publications",
                    "name": name,
                    "question": f"Which months should VAMP expect evidence for {name}: idea/planning, writing, co-author feedback, submission, review, revision, or acceptance?",
                }
            )
        if not _is_answered(publication.get("current_status")):
            questions.append(
                {
                    "id": f"publication_status::{name}",
                    "type": "current_status",
                    "target": "publications",
                    "name": name,
                    "question": f"What is the current status of {name}, and what evidence terms or collaborators should VAMP search for?",
                }
            )
        if not _is_answered(publication.get("target_venue_or_output")):
            questions.append(
                {
                    "id": f"publication_target::{name}",
                    "type": "target_output",
                    "target": "publications",
                    "name": name,
                    "question": f"What is the target venue/output for {name}, if known, and are there project names, journal/book/conference names, or co-authors linked to it?",
                }
            )

    supervision = context.get("supervision") if isinstance(context.get("supervision"), dict) else {}
    if supervision and (supervision.get("status") == "needs_clarification" or not _month_list(supervision.get("active_months"))):
        questions.append(
            {
                "id": "supervision_months",
                "type": "months",
                "target": "supervision",
                "question": "Which months did postgraduate supervision actually happen, and which months were dormant, awaiting registration, or not applicable?",
            }
        )
    if supervision and not _is_answered(supervision.get("stage_by_student")):
        student_hint = ", ".join(str(s) for s in (supervision.get("students") or [])[:6])
        questions.append(
            {
                "id": "supervision_student_stages",
                "type": "student_stages",
                "target": "supervision",
                "question": f"For each supervised student, what stage are they in? Use stages like proposal, scientific committee, ethics, intervention/data collection, analysis, chapter feedback, or submission. Students detected: {student_hint or 'none listed'}",
            }
        )
    if supervision and not _is_answered(supervision.get("evidence_locations")):
        questions.append(
            {
                "id": "supervision_evidence_locations",
                "type": "evidence_locations",
                "target": "supervision",
                "question": "Where should VAMP search for supervision evidence: Outlook student emails, calendar meetings, proposal/chapter documents, ethics/scientific committee messages, or eFundi/Teams?",
            }
        )

    for committee in context.get("committees") or []:
        name = committee.get("name") or "committee"
        if not _month_list(committee.get("active_months")):
            questions.append(
                {
                    "id": f"committee_months::{name}",
                    "type": "months",
                    "target": "committees",
                    "name": name,
                    "question": f"Which months did you actually attend or contribute to {name}, and what abbreviation is used in emails/calendar entries?",
                }
            )

    return questions[:max_questions]
