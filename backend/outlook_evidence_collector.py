from __future__ import annotations

import hashlib
import re
import time
from calendar import month_name, month_abbr, monthrange
from pathlib import Path
from typing import Any, Dict, List, Sequence

try:
    from backend.nwu_people_index import source_context_for_text
except Exception:  # pragma: no cover - collector still works without people index
    source_context_for_text = None


STOPWORDS = {
    "about",
    "across",
    "after",
    "against",
    "already",
    "also",
    "annual",
    "appraisal",
    "approval",
    "approved",
    "because",
    "before",
    "between",
    "cadence",
    "could",
    "criteria",
    "cycle",
    "evidence",
    "expectation",
    "form",
    "general",
    "january",
    "february",
    "march",
    "april",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
    "kpa",
    "minimum",
    "month",
    "output",
    "performance",
    "please",
    "required",
    "review",
    "should",
    "staff",
    "stretch",
    "target",
    "task",
    "teaching",
    "their",
    "there",
    "these",
    "this",
    "through",
    "using",
    "which",
    "year",
}

NWU_JARGON_TERMS: dict[str, set[str]] = {
    # Teaching / LMS
    "efundi": {"efundi", "eFundi", "lms", "learning management system", "sakai", "course site", "module site"},
    "lms": {"efundi", "eFundi", "lms", "learning management system", "sakai", "course site", "module site"},
    "blackboard": {"blackboard", "lms", "learning management system", "course site"},
    "wil": {"wil", "work integrated learning", "teaching practice", "tp"},
    "ror": {"ror", "reception orientation registration", "reception, orientation and registration", "orientation programme", "student orientation"},
    # NWU committees / administration
    "smc": {"smc", "school management committee", "school management", "school committee"},
    "school management committee": {"smc", "school management committee", "school management"},
    "subject group": {"subject group", "subject group meeting", "sg meeting", "sg"},
    "faculty board": {"faculty board", "fb", "faculty board agenda", "faculty board minutes"},
    "faculty forum": {"faculty forum", "forum", "faculty meeting"},
    "research focus area": {"research focus area", "rfa", "sdl", "research entity"},
    "pdp": {"pdp", "professional development plan", "personal development plan"},
    # Research / ethics / projects
    "ethics": {"ethics", "ethics application", "ethics clearance", "hrec", "ethics approval"},
    "intervention": {"intervention", "implementation", "pilot", "fieldwork", "data collection"},
    "publication": {"publication", "manuscript", "article", "draft", "journal", "chapter"},
    "citesaga": {"citesaga", "cite saga", "citation game", "citation"},
    "workready": {"workready", "work ready", "work-readiness", "work readiness"},
    "gbl": {
        "gbl",
        "game based learning",
        "game-based learning",
        "game based pedagogy",
        "gamified learning",
        "gamification",
        "ai gbl",
        "ai and gbl",
        "play-based learning",
        "play based learning",
        "playful learning",
        "serious games",
        "educational game",
        "learning game",
        "vamp",
        "seraph",
        "ai project",
        "ai system",
        "agentic ai",
        "artificial intelligence",
        "llm",
        "prototype",
        "software prototype",
        "invention disclosure",
        "technology disclosure",
        "ip disclosure",
        "d2026",
        "d2026-164",
        "tech transfer",
        "commercialisation",
    },
    # Compliance / institutional shorthand
    "ohs": {"ohs", "occupational health and safety", "safety", "risk assessment"},
    "nrf": {"nrf", "national research foundation", "nrf rating"},
}


GENERIC_MATCH_TERMS = STOPWORDS.union(
    {
        "academic",
        "activity",
        "administration",
        "analysis",
        "class",
        "completion",
        "data",
        "delivery",
        "design",
        "development",
        "faculty",
        "learning",
        "lecture",
        "management",
        "module",
        "planning",
        "preparation",
        "progress",
        "project",
        "regular",
        "report",
        "research",
        "school",
        "semester",
        "student",
        "submission",
        "support",
        "work",
    }
)


KPA_EVIDENCE_PROFILES: dict[str, dict[str, Any]] = {
    "teaching": {
        "markers": {"teach", "teaching", "learning", "curriculum", "module"},
        "evidence_terms": {
            "announcement",
            "assessment",
            "assignment",
            "blackboard",
            "chapter feedback",
            "class list",
            "consultation",
            "course site",
            "content upload",
            "curriculum",
            "efundi",
            "exam",
            "feedback",
            "gradebook",
            "learning unit",
            "internal moderation",
            "lecture slides",
            "lesson plan",
            "lms",
            "mark sheet",
            "marking",
            "marks",
            "memo",
            "memorandum",
            "moderation",
            "moderator",
            "paper",
            "portal site",
            "reading list",
            "resources",
            "rubric",
            "study unit",
            "study guide",
            "student resources",
            "test",
            "thesis",
            "turnitin",
            "wil",
            "work integrated learning",
        },
        "artifact_terms": {
            "attachment",
            "brief",
            "docx",
            "feedback",
            "form",
            "gradebook",
            "memo",
            "minutes",
            "pdf",
            "report",
            "rubric",
            "spreadsheet",
            "study unit",
            "xlsx",
        },
    },
    "research": {
        "markers": {"research", "innovation", "creative", "publication", "conference", "supervision", "postgraduate", "supervisor", "supervisee"},
        "evidence_terms": {
            "accepted",
            "article",
            "book chapter",
            "chapter",
            "citesaga",
            "collaboration",
            "conference",
            "correspondence",
            "draft",
            "ethics",
            "ethics application",
            "ethics clearance",
            "funding",
            "gbl",
            "intervention",
            "intervention status",
            "journal",
            "manuscript",
            "masters",
            "med",
            "nrf",
            "phd",
            "postgraduate",
            "presentation",
            "progress meeting",
            "proposal",
            "proceedings",
            "publication",
            "published",
            "research agenda",
            "research goals",
            "research plan",
            "supervisee",
            "supervision",
            "supervisor",
            "symposium",
            "thesis",
            "dissertation",
            "workready",
            "working paper",
            "writing school",
        },
        "artifact_terms": {
            "abstract",
            "acceptance",
            "article",
            "chapter",
            "draft",
            "feedback",
            "manuscript",
            "minutes",
            "pdf",
            "proposal",
            "pptx",
            "progress",
            "report",
        },
    },
    "leadership": {
        "markers": {"leadership", "administration", "committee", "coordination", "management"},
        "evidence_terms": {
            "agenda",
            "accepted",
            "appointment",
            "attended",
            "attendance",
            "calendar",
            "committee",
            "coordination",
            "coordinator",
            "faculty board",
            "invite",
            "invitation",
            "meeting accepted",
            "meeting invite",
            "minutes",
            "policy",
            "professional development",
            "programme",
            "report",
            "research focus area",
            "school management",
            "smc",
            "subject group",
            "teams meeting",
        },
        "artifact_terms": {"agenda", "appointment", "attendance", "calendar", "circular", "invite", "minutes", "report"},
    },
    "social": {
        "markers": {
            "social",
            "community",
            "industry",
            "engagement",
            "responsiveness",
            "commercialisation",
            "commercialization",
            "technology transfer",
            "tech transfer",
            "service learning",
            "volunteer",
            "disclosure",
        },
        "evidence_terms": {
            "community",
            "engagement",
            "industry",
            "industry partner",
            "project report",
            "responsiveness",
            "commercialisation",
            "commercialization",
            "technology transfer",
            "tech transfer",
            "invention disclosure",
            "technology disclosure",
            "ip disclosure",
            "disclosure",
            "service learning",
            "volunteer work",
            "public engagement",
            "outreach",
            "hannes malan",
        },
        "artifact_terms": {"agreement", "attendance", "disclosure", "letter", "meeting", "report"},
    },
    "ohs": {
        "markers": {"ohs", "occupational", "health", "safety", "compliance"},
        "evidence_terms": {"audit", "compliance", "ohs", "risk assessment", "safety", "training"},
        "artifact_terms": {"attendance", "certificate", "checklist", "form", "risk assessment"},
    },
}


TASK_CATEGORY_TERMS: dict[str, set[str]] = {
    "jan_planning": {
        "announcement",
        "assessment plan",
        "course outline",
        "curriculum design",
        "efundi",
        "learning outcomes",
        "lesson plan",
        "module plan",
        "module planning",
        "portal site",
        "resources",
        "rubric",
        "schedule",
        "study guide",
        "study unit",
        "upload",
    },
    "ror_orientation": {
        "orientation",
        "orientation programme",
        "reception",
        "registration",
        "ror",
        "student orientation",
        "welcome",
    },
    "supervision": {
        "application status",
        "co-promotor",
        "dissertation",
        "ethics",
        "faculty decision",
        "guidance",
        "masters",
        "med",
        "phd",
        "postgraduate",
        "progress",
        "progress meeting",
        "promotor",
        "proposal",
        "research proposal",
        "resume supervision",
        "study leader",
        "studyleader",
        "supervisee",
        "supervision",
        "supervision request",
        "supervisor",
        "thesis",
    },
    "research_pd": {
        "nrf",
        "professional development",
        "research development",
        "research workshop",
        "seminar",
        "training",
        "webinar",
        "workshop",
        "writing retreat",
        "writing school",
    },
    "committee": {
        "agenda",
        "attendance",
        "calendar",
        "committee",
        "faculty forum",
        "invite",
        "invitation",
        "meeting",
        "meeting accepted",
        "meeting invite",
        "mentorship",
        "minutes",
        "professional development",
        "research focus area",
        "school management",
        "smc",
        "subject group",
        "teams meeting",
    },
}


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    text = re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()
    return text


def _tokenize(value: str) -> set[str]:
    tokens = set(re.findall(r"[a-z0-9]{3,}", (value or "").lower()))
    return {token for token in tokens if token not in STOPWORDS}


def _normalize_code(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", value.upper())


def _module_codes(value: str) -> list[str]:
    codes: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"\b([A-Z]{2,})\s*([0-9]{2,})\b", value or ""):
        code = _normalize_code("".join(match.groups()))
        if code and code not in seen:
            seen.add(code)
            codes.append(code)
    return codes


def _phrase_in_text(phrase: str, text_lower: str) -> bool:
    phrase_norm = _normalize_text(phrase).lower()
    if not phrase_norm:
        return False
    if " " in phrase_norm:
        return phrase_norm in text_lower
    return bool(re.search(rf"\b{re.escape(phrase_norm)}\b", text_lower))


def _expanded_jargon_terms(term: str) -> list[str]:
    """Return NWU/local variants for a term without letting generic words drift."""
    term_norm = _normalize_text(term).lower()
    if not term_norm:
        return []

    expanded: list[str] = []
    for key, variants in NWU_JARGON_TERMS.items():
        if (
            term_norm == key
            or _phrase_in_text(key, term_norm)
            or any(_phrase_in_text(variant.lower(), term_norm) for variant in variants)
        ):
            expanded.extend(sorted(variants, key=lambda value: (len(value.split()), len(value))))

    # Keep multi-word variants and known short acronyms; discard single generic words.
    safe: list[str] = []
    known_short = {"fb", "gbl", "nrf", "ohs", "pdp", "rfa", "ror", "sg", "smc", "tp", "wil"}
    seen: set[str] = set()
    for value in expanded:
        value = _normalize_text(value)
        marker = value.lower()
        if not value or marker in seen:
            continue
        if " " not in marker and marker not in known_short and marker in GENERIC_MATCH_TERMS:
            continue
        seen.add(marker)
        safe.append(value)
    return safe


def _plan_kpa_family(plan: Dict[str, Any]) -> str:
    # In the current NWU TA taxonomy the KPA code is reliable; use it before
    # keyword markers so KPA4 "Research Focus Area" committees do not become
    # research tasks.
    code = str(plan.get("kpa_code") or "").upper()
    fallback = {
        "KPA1": "teaching",
        "KPA2": "ohs",
        "KPA3": "research",
        "KPA4": "leadership",
        "KPA5": "social",
    }
    if code in fallback:
        return fallback[code]

    blob = " ".join(
        str(part or "")
        for part in [
            plan.get("kpa_name"),
            plan.get("kpa"),
            plan.get("title"),
            " ".join(plan.get("keywords", []) or []),
        ]
    ).lower()
    for family, profile in KPA_EVIDENCE_PROFILES.items():
        if any(marker in blob for marker in profile["markers"]):
            return family

    return fallback.get(code, "")


def _kpa_profile_for_plan(plan: Dict[str, Any]) -> dict[str, Any]:
    family = _plan_kpa_family(plan)
    return KPA_EVIDENCE_PROFILES.get(family, {})


def _task_category_terms(plan: Dict[str, Any]) -> list[str]:
    """Return task-specific evidence/search terms inferred from the task title."""
    title = _normalize_text(plan.get("title", "")).lower()
    keywords_blob = " ".join(_normalize_text(k) for k in (plan.get("keywords", []) or [])).lower()
    blob = f"{title} {keywords_blob}"
    categories: list[str] = []

    if any(marker in blob for marker in ("jan:", "module planning", "curriculum design", "efundi", "study guide", "reading list", "assessment planning", "rubric")):
        categories.append("jan_planning")
    if any(marker in blob for marker in ("ror", "orientation", "reception", "registration")):
        categories.append("ror_orientation")
    if any(marker in blob for marker in ("postgraduate", "supervision", "supervisor", "supervisee", "masters", "phd", "thesis", "dissertation")):
        categories.append("supervision")
    if "research professional development" in blob or any(marker in blob for marker in ("writing school", "research workshop", "seminar", "webinar")):
        categories.append("research_pd")
    if "committee" in blob or "smc" in blob or any(marker in blob for marker in ("faculty forum", "mentorship", "school management", "subject group", "pdp", "professional development")):
        categories.append("committee")

    terms: list[str] = []
    seen: set[str] = set()
    for category in categories:
        for term in TASK_CATEGORY_TERMS.get(category, set()):
            for candidate in [term, *_expanded_jargon_terms(term)]:
                marker = candidate.lower()
                if marker not in seen:
                    seen.add(marker)
                    terms.append(candidate)
    return terms


def _high_value_plan_terms(plan: Dict[str, Any]) -> list[str]:
    profile = _kpa_profile_for_plan(plan)
    evidence_terms = list(profile.get("evidence_terms") or []) + _task_category_terms(plan)
    keywords = [_normalize_text(k) for k in (plan.get("keywords", []) or [])]
    title = _normalize_text(plan.get("title", ""))
    title_lower = title.lower()

    terms: list[str] = []

    # Prefer task-specific hints that are evidence nouns or project/module names.
    for kw in keywords:
        kw_l = kw.lower()
        if not kw_l or kw_l in GENERIC_MATCH_TERMS:
            continue
        if any(_phrase_in_text(term, kw_l) or _phrase_in_text(kw_l, term) for term in evidence_terms):
            terms.append(kw)

    for term in evidence_terms:
        if _phrase_in_text(term, title_lower) or any(_phrase_in_text(term, k.lower()) for k in keywords):
            terms.append(term)

    # Proper-name project tokens are often the best research/committee queries.
    _KNOWN_SHORT_ACRONYMS = {"gbl", "nrf", "ror", "smc", "wil", "ohs"}
    for phrase in re.findall(r"\b[A-Z][A-Za-z0-9&-]*(?:\s+[A-Z][A-Za-z0-9&-]*){0,3}\b", title):
        phrase = _normalize_text(phrase)
        words = phrase.split()
        # Allow known short acronyms (3 chars) even though they're below the normal threshold
        is_known_acronym = len(words) == 1 and phrase.lower() in _KNOWN_SHORT_ACRONYMS
        if len(phrase) < 4 and not is_known_acronym:
            continue
        if re.fullmatch(r"[A-Z0-9\s-]+", phrase) and not any(word.lower() in _KNOWN_SHORT_ACRONYMS for word in words):
            continue
        if _normalize_code(phrase) in set(_module_codes(title)):
            continue
        if re.fullmatch(r"[A-Z0-9\s]+", phrase) and any(_normalize_code(word) in set(_module_codes(title)) for word in words):
            continue
        if all(word.lower() in GENERIC_MATCH_TERMS for word in words):
            continue
        terms.append(phrase)

    # Staff interview context may add collaborators/approvers as keywords.
    # These are strong search terms for research projects where the email body
    # says "status", "ethics", or "intervention" without repeating the project
    # title in every message.
    if _plan_kpa_family({"kpa_code": plan.get("kpa_code"), "title": title}) == "research":
        terms.extend(_proper_name_keywords(plan))

    # Keep order while removing duplicates.
    deduped: list[str] = []
    seen: set[str] = set()
    expanded_terms: list[str] = []
    for term in terms:
        expanded_terms.append(term)
        expanded_terms.extend(_expanded_jargon_terms(term))

    for term in expanded_terms:
        marker = term.lower()
        if marker not in seen:
            seen.add(marker)
            deduped.append(term)
    return deduped


def _evidence_hits_for_plan(plan: Dict[str, Any], text: str) -> tuple[list[str], list[str]]:
    text_lower = text.lower()
    profile = _kpa_profile_for_plan(plan)
    terms = (
        list(profile.get("evidence_terms") or [])
        + list(profile.get("artifact_terms") or [])
        + _task_category_terms(plan)
    )
    evidence_hits = [term for term in terms if _phrase_in_text(term, text_lower)]
    high_value_hits = [term for term in _high_value_plan_terms(plan) if _phrase_in_text(term, text_lower)]
    return sorted(set(evidence_hits)), sorted(set(high_value_hits))


def _query_term_priority(plan: Dict[str, Any], term: str) -> tuple[int, int, str]:
    term_l = _normalize_text(term).lower()
    family = _plan_kpa_family(plan)
    specific_first = {
        "rubric": 1,
        "moderation": 1,
        "gradebook": 1,
        "marks": 1,
        "efundi": 1,
        "study guide": 1,
        "reading list": 1,
        "lesson plan": 1,
        "citesaga": 1,
        "workready": 1,
        "ai gbl": 1,
        "ai and gbl": 1,
        "game-based learning": 1,
        "game based learning": 1,
        "gamification": 1,
        "play-based learning": 1,
        "playful learning": 1,
        "serious games": 1,
        "vamp": 1,
        "seraph": 1,
        "agentic ai": 1,
        "invention disclosure": 1,
        "technology disclosure": 1,
        "ip disclosure": 1,
        "d2026": 1,
        "d2026-164": 1,
        "tech transfer": 1,
        "gbl": 2,
        "faculty board": 1,
        "minutes": 1,
        "ohs": 1,
        "risk assessment": 1,
        "announcement": 1,
        "content upload": 1,
        "course outline": 1,
        "module plan": 1,
        "module planning": 1,
        "orientation programme": 1,
        "portal site": 1,
        "resources": 2,
        "study unit": 1,
        "med": 2,
        "phd": 2,
        "postgraduate": 0,
        "application status": 0,
        "co-promotor": 0,
        "faculty decision": 0,
        "progress meeting": 1,
        "promotor": 0,
        "proposal": 0,
        "research proposal": 0,
        "resume supervision": 0,
        "study leader": 0,
        "studyleader": 0,
        "supervisee": 1,
        "supervision": 0,
        "supervision request": 0,
        "supervisor": 1,
        "thesis": 0,
        "dissertation": 0,
        # Early-year research planning / ethics / intervention evidence
        "ethics application": 1,
        "ethics clearance": 1,
        "intervention": 2,
        "intervention status": 1,
        "research agenda": 2,
        "research goals": 2,
        "research plan": 1,
        "collaboration": 3,
        "correspondence": 4,
        "research workshop": 1,
        "seminar": 2,
        "webinar": 2,
        "writing school": 1,
        "smc": 0,
        "school management committee": 0,
        "school management": 1,
        "school committee": 1,
        "faculty forum": 1,
        "faculty board": 0,
        "mentorship": 1,
        "professional development": 2,
        "research focus area": 1,
        "rfa": 1,
        "sg": 1,
        "sg meeting": 0,
        "subject group": 0,
        "subject group meeting": 0,
    }
    broad_terms = {
        "agenda",
        "article",
        "book",
        "chapter",
        "committee",
        "assessment",
        "conference",
        "draft",
        "journal",
        "manuscript",
        "meeting",
        "presentation",
        "project",
        "publication",
        "research",
        "submission",
    }
    priority = specific_first.get(term_l, 5)
    if term_l in broad_terms:
        priority = 9
    if family == "research" and any(
        name in term_l
        for name in (
            "citesaga",
            "workready",
            "gbl",
            "prosper",
            "supervision",
            "supervisor",
            "postgraduate",
            "proposal",
            "promotor",
            "co-promotor",
            "study leader",
            "faculty decision",
            "application status",
            "resume supervision",
            "thesis",
            "dissertation",
            "med",
            "phd",
        )
    ):
        priority = 0
    if family == "teaching" and term_l in {"assessment", "lecture"}:
        priority = 8
    return priority, len(term_l.split()), term_l


def _attachment_quality(attachment_names: Sequence[str]) -> tuple[int, list[str]]:
    names_text = " ".join(attachment_names or "").lower()
    if not names_text:
        return 0, []
    strong_terms = {
        "agenda",
        "article",
        "assessment",
        "attendance",
        "brief",
        "certificate",
        "chapter",
        "draft",
        "exam",
        "feedback",
        "gradebook",
        "guide",
        "manuscript",
        "memo",
        "minutes",
        "moderation",
        "presentation",
        "report",
        "rubric",
        "slides",
        "test",
    }
    hits = [term for term in strong_terms if _phrase_in_text(term, names_text)]
    return len(hits), sorted(hits)


def _safe_fragment(value: str, length: int = 48) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", value or "").strip("-._")
    return (text or "artifact")[:length]


def _month_window(month_bucket: str) -> tuple[str, str]:
    year_s, month_s = month_bucket.split("-", 1)
    year = int(year_s)
    month = int(month_s[:2])
    last_day = monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last_day:02d}"


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = (year * 12 + (month - 1)) + delta
    return index // 12, (index % 12) + 1


def _evidence_window_for_plan(month_bucket: str, plan: Dict[str, Any]) -> tuple[str, str]:
    """Return accepted evidence date window for a target task.

    Most tasks are exact-month. Lead/prep tasks, especially January module setup
    and orientation, can have evidence before the month or just after setup
    messages are sent.
    """
    start, end = _month_window(month_bucket)
    categories = set()
    title_blob = f"{plan.get('title', '')} {' '.join(plan.get('keywords', []) or [])}".lower()
    if any(marker in title_blob for marker in ("jan:", "module planning", "curriculum design", "efundi", "study guide", "reading list", "assessment planning", "rubric")):
        categories.add("jan_planning")
    if any(marker in title_blob for marker in ("ror", "orientation", "reception", "registration")):
        categories.add("ror_orientation")
    if not categories:
        return start, end

    year_s, month_s = month_bucket.split("-", 1)
    year, month = int(year_s), int(month_s[:2])
    prev_year, prev_month = _shift_month(year, month, -2)
    _, next_month_end = _month_window(f"{year:04d}-{month:02d}")
    next_year, next_month = _shift_month(year, month, 1)
    next_last = min(14, monthrange(next_year, next_month)[1])
    return f"{prev_year:04d}-{prev_month:02d}-01", f"{next_year:04d}-{next_month:02d}-{next_last:02d}"


def _received_in_month(received_at: str, month_bucket: str) -> bool:
    received = _normalize_text(received_at)
    if not received:
        return False
    if received.startswith(month_bucket):
        return True
    month_start, month_end = _month_window(month_bucket)
    if month_start <= received[:10] <= month_end:
        return True
    return False


def _received_in_plan_window(received_at: str, month_bucket: str, plan: Dict[str, Any]) -> bool:
    received = _normalize_text(received_at)
    if not received:
        return False
    start, end = _evidence_window_for_plan(month_bucket, plan)
    date = received[:10]
    return start <= date <= end


def _first_non_empty_text(page: Any, selectors: Sequence[str]) -> str:
    for selector in selectors:
        try:
            value = page.locator(selector).first.inner_text(timeout=600)
        except Exception:
            continue
        normalized = _normalize_text(value)
        if normalized:
            return normalized
    return ""


def _first_non_empty_attr(page: Any, targets: Sequence[tuple[str, str]]) -> str:
    for selector, attr in targets:
        try:
            value = page.locator(selector).first.get_attribute(attr, timeout=600)
        except Exception:
            continue
        normalized = _normalize_text(value)
        if normalized:
            return normalized
    return ""


def _collect_row_candidates(page: Any) -> list[Any]:
    selectors = [
        # Prefer actual message-list/search-result containers. Broad
        # div[role='main'] rows can include the open reading pane and cause the
        # collector to inspect an unrelated message after a search.
        "div[role='listbox'] [role='option']",
        "div[role='list'] div[role='option']",
        "div[role='list'] div[role='listitem']",
        "[data-app-section='MailList'] [role='option']",
        "[data-app-section='MailList'] [role='listitem']",
        "div[role='main'] div[data-convid]",
        # Classic Outlook fallback.
        "div[role='main'] [role='option']",
    ]
    rows: list[Any] = []
    seen_handles: set[str] = set()
    for selector in selectors:
        locator = page.locator(selector)
        try:
            count = locator.count()
        except Exception:
            count = 0
        for index in range(count):
            candidate = locator.nth(index)
            try:
                handle = candidate.element_handle(timeout=1000)
            except Exception:
                handle = None
            if handle is None:
                continue
            marker = str(id(handle))
            if marker in seen_handles:
                continue
            seen_handles.add(marker)
            rows.append(candidate)
    return rows


def _proper_name_keywords(plan: Dict[str, Any]) -> list[str]:
    names: list[str] = []
    for kw in plan.get("keywords", []) or []:
        text = _normalize_text(kw)
        words = text.split()
        if len(words) < 2 or len(words) > 4:
            continue
        if any(word.lower() in GENERIC_MATCH_TERMS or word.lower() in STOPWORDS for word in words):
            continue
        if not all(re.match(r"^[A-Z][A-Za-z.'-]+$", word) for word in words):
            continue
        names.append(text)

    deduped: list[str] = []
    seen: set[str] = set()
    for name in names:
        marker = name.lower()
        if marker not in seen:
            seen.add(marker)
            deduped.append(name)
    return deduped


def _dismiss_outlook_overlays(page: Any) -> None:
    """Close transient Outlook dialogs that can block the search box."""
    try:
        if page.locator(".fui-DialogSurface__backdrop, [role='dialog']").count() == 0:
            return
    except Exception:
        return

    for selector in [
        "button[aria-label='Close']",
        "button[aria-label*='Close']",
        "button[title='Close']",
        "button[title*='Close']",
        "[role='dialog'] button[aria-label*='Dismiss']",
        "[role='dialog'] button[aria-label*='Cancel']",
    ]:
        try:
            button = page.locator(selector).first
            if button.count() > 0:
                button.click(timeout=1200)
                page.wait_for_timeout(300)
                return
        except Exception:
            continue

    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
    except Exception:
        pass


def _open_search_box(page: Any) -> Any | None:
    _dismiss_outlook_overlays(page)
    # First try to find an already-visible search input
    input_selectors = [
        "input[aria-label*='Search']",
        "input[placeholder*='Search']",
        "div[role='search'] input",
        "input[type='search']",
        # New Outlook (cloud.microsoft)
        "[data-app-section='Search'] input",
        "header input",
    ]
    for selector in input_selectors:
        locator = page.locator(selector).first
        try:
            locator.wait_for(state="visible", timeout=3000)
            return locator
        except Exception:
            continue

    # Newer Outlook Web hides the input behind a search button — click it first
    trigger_selectors = [
        "button[aria-label*='Search']",
        "button[title*='Search']",
        "div[role='search'] button",
        "[data-app-section='Search'] button",
        # New Outlook top bar
        "header button[aria-label*='Search']",
        "[role='search']",
    ]
    for selector in trigger_selectors:
        locator = page.locator(selector).first
        try:
            locator.wait_for(state="visible", timeout=3000)
            locator.click(timeout=3000)
            page.wait_for_timeout(600)
            break
        except Exception:
            continue

    # After clicking the trigger, the input should now be visible
    for selector in input_selectors:
        locator = page.locator(selector).first
        try:
            locator.wait_for(state="visible", timeout=3000)
            return locator
        except Exception:
            continue

    print("[VAMP-Outlook] Could not locate search box — skipping search for this query.", flush=True)
    return None


def _snapshot_row_subjects(page: Any) -> list[str]:
    """Capture the first few visible email-row subjects for change detection."""
    subjects: list[str] = []
    try:
        for sel in [
            "div[role='listbox'] [role='option']",
            "[data-convid]",
            "div[role='listitem']",
        ]:
            items = page.locator(sel).all()
            if items:
                for item in items[:6]:
                    try:
                        subjects.append(item.inner_text(timeout=500)[:80])
                    except Exception:
                        pass
                if subjects:
                    break
    except Exception:
        pass
    return subjects


def _run_outlook_search(page: Any, query: str) -> bool:
    """Type *query* into the Outlook search box and wait for results.

    One Outlook (cloud.microsoft) renders search results in-place without changing
    the URL.  We snapshot the inbox rows before submitting and wait until the list
    content changes — that is our only reliable signal that results have loaded.

    IMPORTANT: do NOT press Escape before Enter. Escape in One Outlook clears the
    search box and returns to inbox, so a subsequent Enter submits an empty search.
    """
    search_box = _open_search_box(page)
    if search_box is None:
        return False
    try:
        _dismiss_outlook_overlays(page)
        # --- snapshot inbox rows so we can detect when they change ---
        rows_before = _snapshot_row_subjects(page)

        try:
            search_box.click(timeout=1500)
        except Exception:
            _dismiss_outlook_overlays(page)
            search_box.click(timeout=2500)
        try:
            search_box.fill("", timeout=1500)
        except Exception:
            pass
        search_box.press("Control+a")
        search_box.press("Backspace")
        # Short delay between chars helps One Outlook's autocomplete settle
        search_box.type(query[:180], delay=30)
        # Wait for autocomplete to appear then press Enter to submit.
        # Do NOT press Escape first — that cancels the search in One Outlook.
        page.wait_for_timeout(400)
        search_box.press("Enter")

        # Wait up to 8 s for rows to change (URL never changes in One Outlook)
        rows_changed = False
        for _ in range(32):
            page.wait_for_timeout(250)
            rows_after = _snapshot_row_subjects(page)
            if rows_after and rows_after != rows_before:
                rows_changed = True
                break

        if not rows_changed:
            # Fallback: try clicking a visible search-submit button
            for btn_sel in [
                "button[aria-label*='Search']",
                "button[type='submit']",
                "[role='search'] button",
            ]:
                try:
                    btn = page.locator(btn_sel).first
                    btn.click(timeout=1500)
                    page.wait_for_timeout(3000)
                    rows_after = _snapshot_row_subjects(page)
                    if rows_after != rows_before:
                        rows_changed = True
                    break
                except Exception:
                    continue

        # Extra settling time for results to fully populate
        page.wait_for_timeout(1500)
        print(
            f"[VAMP-Outlook] Search '{query[:60]}': URL={page.url[:80]} "
            f"rows_changed={rows_changed}",
            flush=True,
        )
        return True
    except Exception as exc:
        print(f"[VAMP-Outlook] _run_outlook_search error: {exc}", flush=True)
        return False



def _clear_outlook_search(page: Any, outlook_url: str) -> None:
    search_box = _open_search_box(page)
    if search_box is not None:
        try:
            search_box.click(timeout=1200)
            search_box.press("Control+a")
            search_box.press("Backspace")
            search_box.press("Enter")
            page.wait_for_timeout(1500)
            return
        except Exception:
            pass
    try:
        page.goto(outlook_url, wait_until="domcontentloaded")
        _wait_for_outlook_mailbox(page, timeout_ms=120000)
        page.wait_for_timeout(1200)
    except Exception:
        return


def _wait_for_outlook_mailbox(page: Any, timeout_ms: int = 900000) -> None:
    """Wait until the Outlook Web mailbox is ready.

    Strategy (in priority order):
    1. URL is on outlook.office.com (any path) and not on a login / consent page.
    2. After that URL condition is met, confirm at least one well-known DOM selector
       is present OR wait up to 6 s and proceed anyway (handles selector drift in
       newer Outlook Web layouts).
    """
    dom_selectors = [
        # Classic Outlook Web (office.com)
        "div[role='main'] [role='row']",
        "div[role='main'] [role='option']",
        "div[role='main'] div[data-convid]",
        "div[role='listbox'] [role='option']",
        "button[aria-label*='New mail']",
        "button[title*='New mail']",
        "div[aria-label*='Message list']",
        "div[aria-label*='Inbox']",
        "div[data-app-section='MessageList']",
        "input[aria-label*='Search']",
        "input[placeholder*='Search']",
        # New "One Outlook" (cloud.microsoft)
        "div[role='list'] div[role='option']",
        "div[role='list'] div[role='listitem']",
        "[data-app-section='MailList']",
        "[aria-label*='Mail list']",
        "button[aria-label*='New message']",
        "button[aria-label*='Compose']",
        "input[type='search']",
    ]
    LOGGED_IN_HOSTS = (
        "outlook.office.com",
        "outlook.office365.com",
        "outlook.live.com",
        "outlook.cloud.microsoft",   # new "One Outlook"
        "outlook.microsoft.com",
    )
    LOGIN_FRAGMENTS = ("login.microsoftonline.com", "login.live.com", "account.microsoft.com",
                       "login.microsoft", "/common/oauth2", "/kmsi", "sign in", "sign-in")

    deadline = time.monotonic() + (timeout_ms / 1000)
    on_mail_page_since: float | None = None
    last_url = ""

    while time.monotonic() < deadline:
        try:
            current_url = page.url or ""
            current_title = page.title().lower()

            if current_url != last_url:
                print(f"[VAMP-Outlook] URL: {current_url[:120]}  title: {current_title[:60]}", flush=True)
                last_url = current_url

            is_on_host = any(h in current_url for h in LOGGED_IN_HOSTS)
            is_login_page = any(f in current_url.lower() or f in current_title for f in LOGIN_FRAGMENTS)

            if is_on_host and not is_login_page:
                # We're on the Outlook domain and past the login wall
                if on_mail_page_since is None:
                    on_mail_page_since = time.monotonic()
                    print("[VAMP-Outlook] Reached Outlook. Waiting for mailbox UI…", flush=True)

                # Check DOM selectors for a quicker confirmation
                for selector in dom_selectors:
                    try:
                        if page.locator(selector).count() > 0:
                            print(f"[VAMP-Outlook] Mailbox ready (selector: {selector})", flush=True)
                            return
                    except Exception:
                        continue

                # Fallback: if we've been past login for ≥6 s, proceed anyway
                if time.monotonic() - on_mail_page_since >= 6.0:
                    # Log a sample of interactive elements to help tune selectors
                    try:
                        roles = page.evaluate("""() => {
                            const els = document.querySelectorAll('[role]');
                            const counts = {};
                            els.forEach(e => { const r = e.getAttribute('role'); counts[r] = (counts[r]||0)+1; });
                            return Object.entries(counts).sort((a,b)=>b[1]-a[1]).slice(0,12).map(e=>e[0]+'='+e[1]).join(', ');
                        }""")
                        print(f"[VAMP-Outlook] Page roles: {roles}", flush=True)
                    except Exception:
                        pass
                    print("[VAMP-Outlook] Mailbox selector not matched — proceeding anyway.", flush=True)
                    return
            else:
                on_mail_page_since = None  # reset if we navigate away (e.g. consent redirects)

        except Exception as exc:
            print(f"[VAMP-Outlook] Wait loop error: {exc}", flush=True)
            # If the page/browser itself was closed, stop waiting immediately
            if "TargetClosedError" in type(exc).__name__ or "closed" in str(exc).lower():
                raise

        try:
            page.wait_for_timeout(1500)
        except Exception as exc:
            if "TargetClosedError" in type(exc).__name__ or "closed" in str(exc).lower():
                raise
            # other minor errors — keep looping

    raise RuntimeError(
        "Outlook mailbox did not become ready within the timeout window. "
        "Complete login in the Playwright-opened browser window and retry."
    )


def _guess_row_fields(row_text: str) -> tuple[str, str]:
    lines = [line for line in row_text.splitlines() if _normalize_text(line)]
    if not lines:
        return "", ""
    if len(lines) == 1:
        return lines[0], ""
    return _normalize_text(lines[1]), _normalize_text(lines[0])


def _extract_date_from_text(text: str) -> str:
    """Return first MM/DD/YYYY date found in text as YYYY-MM-DD, or '' if none."""
    m = re.search(r'\b(\d{1,2})/(\d{1,2})/(\d{4})\b', text)
    if m:
        month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31 and 1900 <= year <= 2100:
            return f"{year:04d}-{month:02d}-{day:02d}"
    month_lookup = {
        name.lower(): idx
        for idx, name in enumerate(month_name)
        if name
    }
    month_lookup.update(
        {
            name.lower(): idx
            for idx, name in enumerate(month_abbr)
            if name
        }
    )
    month_names = "|".join(sorted(month_lookup, key=len, reverse=True))
    m = re.search(rf"\b(\d{{1,2}})\s+({month_names})\s+(\d{{4}})\b", text or "", re.I)
    if not m:
        m = re.search(rf"\b({month_names})\s+(\d{{1,2}}),?\s+(\d{{4}})\b", text or "", re.I)
        if m:
            month = month_lookup[m.group(1).lower()]
            day = int(m.group(2))
            year = int(m.group(3))
            if 1 <= day <= 31 and 1900 <= year <= 2100:
                return f"{year:04d}-{month:02d}-{day:02d}"
    else:
        day = int(m.group(1))
        month = month_lookup[m.group(2).lower()]
        year = int(m.group(3))
        if 1 <= day <= 31 and 1900 <= year <= 2100:
            return f"{year:04d}-{month:02d}-{day:02d}"
    return ""


def _extract_row_date_from_text(text: str, month_bucket: str) -> str:
    """Return a row-list date as YYYY-MM-DD when Outlook omits the year.

    Outlook message-list rows often render dates like "Tue 5/5" or "2/13/2026".
    For a targeted month scan, treating short M/D dates as the target year lets
    us skip obvious out-of-month rows before opening each message.
    """
    full = _extract_date_from_text(text)
    if full:
        return full

    year_s, _ = month_bucket.split("-", 1)
    year = int(year_s)
    m = re.search(r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)?\s*(\d{1,2})/(\d{1,2})(?!/\d)\b", text, re.I)
    if not m:
        return ""
    month, day = int(m.group(1)), int(m.group(2))
    if 1 <= month <= 12 and 1 <= day <= 31:
        return f"{year:04d}-{month:02d}-{day:02d}"
    return ""


def _collect_attachment_names(page: Any) -> list[str]:
    selectors = [
        "button[aria-label*='Attachment']",
        "button[title*='Attachment']",
        "div[data-app-section='Attachment'] button",
        "div[data-app-section='Attachment'] a",
        "div[aria-label*='Attachment'] button",
        "div[aria-label*='Attachment'] a",
    ]
    names: list[str] = []
    for selector in selectors:
        locator = page.locator(selector)
        try:
            count = locator.count()
        except Exception:
            count = 0
        for index in range(count):
            try:
                value = _normalize_text(locator.nth(index).inner_text(timeout=750))
            except Exception:
                value = ""
            if value and value not in names:
                names.append(value)
    return names


def _download_visible_attachments(page: Any, target_dir: Path) -> list[str]:
    target_dir.mkdir(parents=True, exist_ok=True)
    selectors = [
        "button[aria-label*='Download']",
        "button[title*='Download']",
        "a[download]",
    ]
    saved: list[str] = []
    seen_names: set[str] = set()
    for selector in selectors:
        locator = page.locator(selector)
        try:
            count = locator.count()
        except Exception:
            count = 0
        for index in range(count):
            button = locator.nth(index)
            try:
                with page.expect_download(timeout=5000) as download_info:
                    button.click(timeout=2000)
                download = download_info.value
                filename = download.suggested_filename
                if not filename or filename in seen_names:
                    continue
                seen_names.add(filename)
                download.save_as(str(target_dir / filename))
                saved.append(filename)
            except Exception:
                continue
    return saved


def _plan_tokens(plan: Dict[str, Any]) -> set[str]:
    parts: list[str] = [plan.get("title", ""), plan.get("kpa_name", ""), plan.get("kpa", "")]
    parts.extend(plan.get("keywords", []) or [])
    return {token for token in _tokenize(" ".join(parts)) if token not in GENERIC_MATCH_TERMS}


def _search_query_for_plan(plan: Dict[str, Any], month_bucket: str | None = None) -> str:
    """Return a short, high-signal Outlook search query (no date filters).

    Rules (in priority order):
    1. Module/project/committee name plus the strongest evidence noun.
    2. Multi-word specific phrases from keywords (quoted) — e.g. "Faculty Board".
    3. First keyword that is neither a stopword nor a generic work-verb.
    Date-range filtering is done post-collection by _received_in_month, NOT here —
    Outlook Web's UI search box does not reliably honour `received:>=ISO-date` syntax.
    """
    title = plan.get("title", "")
    keywords = plan.get("keywords", []) or []
    high_value_terms = _high_value_plan_terms(plan)

    # 1. Module codes are precise, but too broad on their own. Pair them with
    # a task evidence noun when possible: "HISE312 rubric", "HISE411 marks".
    codes = _module_codes(title + " " + " ".join(keywords))
    if codes:
        for term in sorted(high_value_terms, key=lambda value: _query_term_priority(plan, value)):
            term = _normalize_text(term)
            if term and len(term) >= 3 and term.lower() not in GENERIC_MATCH_TERMS:
                return f"{codes[0]} {term}"
        return codes[0]

    # 2. Project/publication/committee names from title or hints.
    for term in sorted(high_value_terms, key=lambda value: _query_term_priority(plan, value)):
        term = _normalize_text(term)
        if not term or term.lower() in GENERIC_MATCH_TERMS:
            continue
        if " " in term:
            return f'"{term}"'
        return term

    _GENERIC = {
        "lecture", "assessment", "project", "progress", "data", "analysis",
        "training", "planning", "report", "module", "class", "semester",
        "meeting", "minutes", "design", "learning", "delivery", "check",
        "preparation", "start", "completion", "submission", "presentation",
        "reception", "registration", "orientation", "review", "marking",
        "research", "supervision", "student", "activity", "development",
        "support", "service", "management", "academic", "work",
    }

    # 2. Multi-word specific phrase (quoted) — only if neither word is generic
    for kw in keywords:
        kw = _normalize_text(kw).strip()
        if not kw or kw.lower() in STOPWORDS:
            continue
        words = kw.split()
        if len(words) >= 2 and not any(w.lower() in _GENERIC or w.lower() in STOPWORDS for w in words):
            return f'"{kw}"'

    # 3. First non-generic, non-stopword keyword (≥3 chars to include acronyms like OHS, NRF)
    for kw in keywords:
        kw = _normalize_text(kw).strip()
        if kw and len(kw) >= 3 and kw.lower() not in STOPWORDS and kw.lower() not in _GENERIC:
            return kw

    # 4. Last resort: any keyword that isn't a stopword
    for kw in keywords:
        kw = _normalize_text(kw).strip()
        if kw and len(kw) >= 3 and kw.lower() not in STOPWORDS:
            return kw

    return ""


def _search_queries_for_plan(
    plan: Dict[str, Any], month_bucket: str | None = None, max_queries: int = 3
) -> list[str]:
    """Return a small ordered set of targeted queries for a plan.

    A single broad query like HISE312 floods the collector. A single narrow query
    like HISE312 eFundi can miss a stronger artifact such as a moderation report.
    This keeps the set small while covering the most likely evidence pieces.
    """
    title = plan.get("title", "")
    keywords = plan.get("keywords", []) or []
    codes = _module_codes(title + " " + " ".join(keywords))
    terms = [
        _normalize_text(term)
        for term in sorted(_high_value_plan_terms(plan), key=lambda value: _query_term_priority(plan, value))
    ]
    terms = [term for term in terms if term and term.lower() not in GENERIC_MATCH_TERMS]

    broad_query_terms = {
        "agenda",
        "article",
        "book",
        "chapter",
        "committee",
        "draft",
        "journal",
        "manuscript",
        "meeting",
        "minutes",
        "project",
        "publication",
        "report",
        "research",
        "submission",
    }
    specific_terms = [term for term in terms if term.lower() not in broad_query_terms]
    if specific_terms:
        terms = specific_terms + [term for term in terms if term.lower() in broad_query_terms]

    collaborator_terms = [_normalize_text(term) for term in _proper_name_keywords(plan)]
    collaborator_terms = [term for term in collaborator_terms if term]
    if collaborator_terms and _plan_kpa_family(plan) == "research":
        # Keep the official project/status queries first, then try named
        # collaborators before broad research words consume the query budget.
        terms_without_collaborators = [term for term in terms if term not in collaborator_terms]
        terms = terms_without_collaborators[:5] + collaborator_terms[:4] + terms_without_collaborators[5:]

    category_terms = [
        _normalize_text(term)
        for term in sorted(_task_category_terms(plan), key=lambda value: _query_term_priority(plan, value))
    ]
    category_terms = [term for term in category_terms if term and term.lower() not in GENERIC_MATCH_TERMS]

    queries: list[str] = []
    if codes and terms:
        for term in terms:
            queries.append(f"{codes[0]} {term}")
            if len(queries) >= max_queries:
                break
    elif terms:
        for term in terms[:max_queries]:
            queries.append(f'"{term}"' if " " in term else term)

    # Title category fallbacks: these catch the language Outlook actually uses
    # when expectations have no explicit hints.
    if codes and category_terms:
        for term in category_terms:
            queries.append(f"{codes[0]} {term}")
            if len(queries) >= max_queries + 2:
                break
    elif category_terms:
        for term in category_terms[: max_queries + 2]:
            queries.append(f'"{term}"' if " " in term else term)

    primary = _search_query_for_plan(plan, month_bucket=month_bucket)
    if primary:
        queries.insert(0, primary)

    deduped: list[str] = []
    seen: set[str] = set()
    for query in queries:
        marker = query.lower()
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(query)
        if len(deduped) >= max_queries:
            break
    return deduped


def describe_search_plan_queries(
    search_plans: Sequence[Dict[str, Any]],
    *,
    month_bucket: str | None = None,
    max_queries_per_plan: int = 5,
) -> list[Dict[str, Any]]:
    """Return auditable Outlook query diagnostics for each search plan."""
    diagnostics: list[Dict[str, Any]] = []
    for plan in search_plans:
        diagnostics.append(
            {
                "task_id": plan.get("task_id"),
                "kpa_code": plan.get("kpa_code"),
                "title": plan.get("title", ""),
                "family": _plan_kpa_family(plan),
                "category_terms": _task_category_terms(plan),
                "high_value_terms": _high_value_plan_terms(plan),
                "queries": _search_queries_for_plan(
                    plan,
                    month_bucket=month_bucket,
                    max_queries=max_queries_per_plan,
                ),
            }
        )
    return diagnostics


def _match_candidate_to_plans(
    *,
    month_bucket: str,
    candidate_text: str,
    attachment_names: Sequence[str],
    received_at: str,
    plans: Sequence[Dict[str, Any]],
) -> tuple[list[str], str | None, str, list[Dict[str, Any]]]:
    all_text = candidate_text + " " + " ".join(attachment_names)
    all_text_lower = all_text.lower()
    candidate_tokens = {token for token in _tokenize(all_text) if token not in GENERIC_MATCH_TERMS}
    candidate_codes = set(_module_codes(all_text))
    attachment_score, attachment_hits = _attachment_quality(attachment_names)

    scored: list[tuple[float, Dict[str, Any], dict[str, Any]]] = []
    for plan in plans:
        # Most tasks require exact-month evidence. Lead/prep tasks such as
        # January module setup can accept a bounded pre/post window.
        if received_at:
            _r = _normalize_text(received_at)
            if len(_r) >= 7 and not _received_in_plan_window(_r, month_bucket, plan):
                continue

        tokens = _plan_tokens(plan)
        overlap = candidate_tokens.intersection(tokens)
        plan_text = " ".join([plan.get("title", ""), " ".join(plan.get("keywords", []) or [])])
        plan_codes = set(_module_codes(plan_text))
        module_hits = sorted(candidate_codes.intersection(plan_codes))
        evidence_hits, high_value_hits = _evidence_hits_for_plan(plan, all_text)
        title_l = (plan.get("title") or "").lower()
        if any(marker in title_l for marker in ("ror", "orientation", "reception", "registration")):
            if not any(_phrase_in_text(term, all_text_lower) for term in TASK_CATEGORY_TERMS["ror_orientation"]):
                continue
        if any(marker in title_l for marker in ("postgraduate", "supervision", "supervisor", "supervisee")):
            if not any(_phrase_in_text(term, all_text_lower) for term in TASK_CATEGORY_TERMS["supervision"]):
                continue
        if "workready" in title_l:
            workready_hit = any(
                _phrase_in_text(term, all_text_lower)
                for term in ("workready", "work ready", "work-readiness", "work readiness")
            )
            collaborator_hit = any(
                _phrase_in_text(name, all_text_lower)
                for name in _proper_name_keywords(plan)
            )
            research_context_hit = any(
                _phrase_in_text(term, all_text_lower)
                for term in (
                    "ethics",
                    "intervention",
                    "publication",
                    "article",
                    "manuscript",
                    "project status",
                    "project planning",
                    "research",
                    "work readiness",
                )
            )
            if not workready_hit and not (collaborator_hit and research_context_hit):
                continue
        if "citesaga" in title_l or "cite saga" in title_l:
            if not any(_phrase_in_text(term, all_text_lower) for term in ("citesaga", "cite saga", "citation game", "aosis")):
                continue
        if any(marker in title_l for marker in ("ai and gbl", "ai gbl", "gbl project")):
            if not any(
                _phrase_in_text(term, all_text_lower)
                for term in (
                    "ai gbl",
                    "ai and gbl",
                    "gbl",
                    "game-based learning",
                    "game based learning",
                    "gamification",
                    "play-based learning",
                    "play based learning",
                    "playful learning",
                    "serious games",
                    "educational game",
                    "learning game",
                    "vamp",
                    "seraph",
                    "agentic ai",
                    "ai project",
                    "ai system",
                    "prototype",
                    "invention disclosure",
                    "technology disclosure",
                    "ip disclosure",
                    "d2026",
                    "d2026-164",
                    "tech transfer",
                    "commercialisation",
                )
            ):
                continue

        # Explicit phrase hits catch values such as "Faculty Board", "AI GBL",
        # and "study guide" that token overlap handles poorly.
        phrase_hits = [
            term
            for term in _high_value_plan_terms(plan)
            if " " in term and _phrase_in_text(term, all_text_lower)
        ]

        if not any([overlap, module_hits, evidence_hits, high_value_hits, attachment_hits, phrase_hits]):
            continue

        score = 0.0
        score += 0.55 * len(overlap)
        score += 3.0 * len(module_hits)
        score += 1.25 * len(evidence_hits)
        score += 1.75 * len(high_value_hits)
        score += 1.35 * attachment_score
        score += 1.5 * len(phrase_hits)
        if plan.get("kpa_code"):
            score += 0.25

        # Body-only Outlook messages are useful, but they need more than broad
        # vocabulary. Attachments can pass with slightly less text because the
        # filename itself is often the evidence artifact.
        threshold = 2.0 if attachment_names else 2.75
        if plan_codes and module_hits:
            threshold -= 0.5
        if high_value_hits or phrase_hits:
            threshold -= 0.35
        if score < threshold:
            continue

        quality = {
            "matched_terms": sorted(overlap),
            "module_hits": module_hits,
            "evidence_hits": evidence_hits,
            "attachment_hits": attachment_hits,
            "phrase_hits": sorted(set(phrase_hits)),
            "kpa_family": _plan_kpa_family(plan),
        }
        scored.append((score, plan, quality))

    scored.sort(key=lambda item: item[0], reverse=True)
    matched = []
    task_ids: list[str] = []
    kpa_hint_code = None
    reason = ""
    for score, plan, quality in scored[:5]:
        task_ids.append(plan["task_id"])
        matched_terms = sorted(
            set(
                quality["matched_terms"]
                + quality["module_hits"]
                + quality["evidence_hits"]
                + quality["attachment_hits"]
                + quality["phrase_hits"]
            )
        )
        matched.append(
            {
                "task_id": plan["task_id"],
                "kpa_code": plan.get("kpa_code"),
                "title": plan.get("title", ""),
                "score": round(score, 2),
                "matched_terms": matched_terms,
                "match_quality": quality,
            }
        )
        if not kpa_hint_code and plan.get("kpa_code"):
            kpa_hint_code = plan["kpa_code"]

    if matched:
        top = matched[0]
        reason = (
            f"matched task '{top['title']}' with evidence signals: "
            f"{', '.join(top['matched_terms'][:7])}"
        )

    return task_ids, kpa_hint_code, reason, matched


# ---------------------------------------------------------------------------
# Microsoft Graph API helpers — replaces Playwright DOM scraping for search
# ---------------------------------------------------------------------------

def _intercept_graph_token(page: Any, timeout_ms: int = 20000) -> str | None:
    """Listen to outgoing network requests and capture a Bearer token usable with Graph API.

    One Outlook (cloud.microsoft) calls various MS APIs on page load. We capture
    ALL Bearer tokens and then try each against graph.microsoft.com/v1.0/me.
    """
    import time as _time
    import requests as _req

    # Collect (token, url) pairs — multiple tokens may appear
    all_tokens: dict[str, str] = {}  # token -> first url seen

    _KNOWN_API_HOSTS = (
        "graph.microsoft.com",
        "substrate.office.com",
        "outlook.office.com",
        "outlook.office365.com",
        "outlook.cloud.microsoft",
        "office.com",
        "microsoft.com",
    )

    def _on_request(request: Any) -> None:
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            return
        tok = auth[7:]
        if tok in all_tokens:
            return
        url = request.url
        if any(h in url for h in _KNOWN_API_HOSTS):
            all_tokens[tok] = url
            print(f"[VAMP-Graph] Captured Bearer token from: {url[:100]}", flush=True)

    page.on("request", _on_request)
    try:
        try:
            page.reload(wait_until="domcontentloaded")
        except Exception:
            pass
        deadline = _time.time() + timeout_ms / 1000
        while len(all_tokens) < 5 and _time.time() < deadline:
            page.wait_for_timeout(400)
    finally:
        try:
            page.remove_listener("request", _on_request)
        except Exception:
            pass

    if not all_tokens:
        print("[VAMP-Graph] No Bearer token intercepted from network requests", flush=True)
        return None

    # Prefer graph.microsoft.com tokens first
    for tok, url in all_tokens.items():
        if "graph.microsoft.com" in url:
            print(f"[VAMP-Graph] Using graph.microsoft.com token (len={len(tok)})", flush=True)
            return tok

    # Try each token against Graph API /me to find one that works
    for tok, url in all_tokens.items():
        try:
            r = _req.get(
                "https://graph.microsoft.com/v1.0/me",
                headers={"Authorization": f"Bearer {tok}"},
                timeout=8,
            )
            if r.status_code == 200:
                print(f"[VAMP-Graph] Token from {url[:80]} validates against Graph API", flush=True)
                return tok
            print(f"[VAMP-Graph] Token from {url[:60]} → HTTP {r.status_code}", flush=True)
        except Exception as e:
            print(f"[VAMP-Graph] Token validation error: {e}", flush=True)

    print("[VAMP-Graph] No captured token validates against Graph API", flush=True)
    return None



def _graph_search_messages(
    token: str,
    query: str,
    max_results: int = 25,
) -> list[Dict[str, Any]]:
    """Search Outlook messages via the Graph API. Returns a list of message objects."""
    import requests as _req

    params: Dict[str, Any] = {
        "$top": min(max_results, 25),
        "$select": "id,subject,from,sender,receivedDateTime,body,hasAttachments",
        "$orderby": "receivedDateTime desc",
    }
    if query:
        params["$search"] = f'"{query}"'

    headers = {
        "Authorization": f"Bearer {token}",
        "ConsistencyLevel": "eventual",
    }

    try:
        resp = _req.get(
            "https://graph.microsoft.com/v1.0/me/messages",
            headers=headers,
            params=params,
            timeout=20,
        )
        if resp.status_code == 401:
            print("[VAMP-Graph] 401 Unauthorized — token expired or wrong audience", flush=True)
            return []
        if not resp.ok:
            print(f"[VAMP-Graph] Error {resp.status_code}: {resp.text[:300]}", flush=True)
            return []
        messages = resp.json().get("value", [])
        print(f"[VAMP-Graph] '{query}' → {len(messages)} messages", flush=True)
        return messages
    except Exception as exc:
        print(f"[VAMP-Graph] Request error: {exc}", flush=True)
        return []


def _graph_calendar_view_events(
    token: str,
    month_bucket: str,
    max_results: int = 100,
) -> list[Dict[str, Any]]:
    """Return calendar events for the target month via Microsoft Graph."""
    import requests as _req

    start, end = _month_window(month_bucket)
    params: Dict[str, Any] = {
        "startDateTime": f"{start}T00:00:00",
        "endDateTime": f"{end}T23:59:59",
        "$top": min(max_results, 100),
        "$select": "id,subject,bodyPreview,body,start,end,location,organizer,attendees,responseStatus,isOnlineMeeting,onlineMeetingProvider,webLink",
        "$orderby": "start/dateTime",
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Prefer": 'outlook.timezone="Africa/Johannesburg"',
    }

    try:
        resp = _req.get(
            "https://graph.microsoft.com/v1.0/me/calendarView",
            headers=headers,
            params=params,
            timeout=20,
        )
        if resp.status_code == 401:
            print("[VAMP-Graph] Calendar 401 Unauthorized — token expired or wrong audience", flush=True)
            return []
        if not resp.ok:
            print(f"[VAMP-Graph] Calendar error {resp.status_code}: {resp.text[:300]}", flush=True)
            return []
        events = resp.json().get("value", [])
        print(f"[VAMP-Graph] calendarView {month_bucket} → {len(events)} events", flush=True)
        return events
    except Exception as exc:
        print(f"[VAMP-Graph] Calendar request error: {exc}", flush=True)
        return []


def _event_text_for_matching(event: Dict[str, Any]) -> tuple[str, list[str], str]:
    subject = event.get("subject") or ""
    location = (event.get("location") or {}).get("displayName") or ""
    organizer_obj = (event.get("organizer") or {}).get("emailAddress") or {}
    organizer = " ".join([organizer_obj.get("name", ""), organizer_obj.get("address", "")]).strip()
    response = (event.get("responseStatus") or {}).get("response") or ""
    attendees = []
    for attendee in event.get("attendees") or []:
        email = (attendee.get("emailAddress") or {})
        status = (attendee.get("status") or {}).get("response") or ""
        attendees.append(" ".join([email.get("name", ""), email.get("address", ""), status]).strip())
    body_preview = event.get("bodyPreview") or ""
    body_raw = (event.get("body") or {}).get("content") or ""
    body_text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body_raw)).strip()
    online = "online teams meeting" if event.get("isOnlineMeeting") else ""
    blob = " ".join(
        part
        for part in [
            subject,
            location,
            organizer,
            response,
            " ".join(attendees),
            body_preview,
            body_text,
            online,
            event.get("onlineMeetingProvider") or "",
        ]
        if part
    )
    attachment_names = ["calendar appointment", "meeting invite"]
    if response:
        attachment_names.append(f"response {response}")
    if event.get("isOnlineMeeting"):
        attachment_names.append("Teams meeting")
    start = ((event.get("start") or {}).get("dateTime") or "")[:10]
    return blob, attachment_names, start


def _source_context(candidate_text: str, *, source: str = "") -> dict[str, Any]:
    if source_context_for_text is None:
        return {
            "source_trust_tier": "C",
            "confidence_boost": 0.0,
            "reasons": [],
            "people_matches": [],
        }
    try:
        return source_context_for_text(candidate_text, source=source)
    except Exception:
        return {
            "source_trust_tier": "C",
            "confidence_boost": 0.0,
            "reasons": [],
            "people_matches": [],
        }


def _calendar_event_artifact(event: Dict[str, Any], target_dir: Path) -> str:
    subject = event.get("subject") or "calendar_event"
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{_safe_fragment(subject)}.txt"
    organizer = ((event.get("organizer") or {}).get("emailAddress") or {})
    attendees = []
    for attendee in event.get("attendees") or []:
        email = attendee.get("emailAddress") or {}
        status = attendee.get("status") or {}
        attendees.append(
            f"- {email.get('name','')} <{email.get('address','')}>: {status.get('response','')}"
        )
    body = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", ((event.get("body") or {}).get("content") or ""))).strip()
    path.write_text(
        "\n".join(
            [
                f"Subject: {subject}",
                f"Start: {((event.get('start') or {}).get('dateTime') or '')}",
                f"End: {((event.get('end') or {}).get('dateTime') or '')}",
                f"Location: {((event.get('location') or {}).get('displayName') or '')}",
                f"Organizer: {organizer.get('name','')} <{organizer.get('address','')}>",
                f"Response: {((event.get('responseStatus') or {}).get('response') or '')}",
                f"Online: {event.get('isOnlineMeeting')}",
                "",
                "Attendees:",
                *attendees,
                "",
                "Body:",
                body or event.get("bodyPreview") or "",
            ]
        ),
        encoding="utf-8",
    )
    return str(path)


def _graph_get_attachments(token: str, message_id: str) -> list[Dict[str, Any]]:
    """Return non-inline attachment metadata for a message."""
    import requests as _req

    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = _req.get(
            f"https://graph.microsoft.com/v1.0/me/messages/{message_id}/attachments",
            headers=headers,
            params={"$select": "id,name,contentType,size,isInline"},
            timeout=15,
        )
        if not resp.ok:
            return []
        return [a for a in resp.json().get("value", []) if not a.get("isInline", False)]
    except Exception:
        return []


def _graph_download_attachment(
    token: str, message_id: str, attachment_id: str, target_path: Path
) -> bool:
    """Download one attachment (base64-encoded in contentBytes) and save to target_path."""
    import requests as _req, base64

    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = _req.get(
            f"https://graph.microsoft.com/v1.0/me/messages/{message_id}/attachments/{attachment_id}",
            headers=headers,
            timeout=30,
        )
        if not resp.ok:
            return False
        content_bytes_b64 = resp.json().get("contentBytes")
        if not content_bytes_b64:
            return False
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(base64.b64decode(content_bytes_b64))
        return True
    except Exception:
        return False


def collect_outlook_candidates(
    *,
    month_bucket: str,
    search_plans: Sequence[Dict[str, Any]],
    storage_state: str | None = None,
    downloads_dir: str | None = None,
    max_messages: int = 25,
    headless: bool = False,
    outlook_url: str = "https://outlook.office.com/mail/",
    include_body_only_candidates: bool = True,
    include_calendar_events: bool = True,
) -> list[Dict[str, Any]]:
    try:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
    except Exception as exc:
        raise RuntimeError(
            "Outlook collection requires Playwright. Install it with: pip install playwright && playwright install chromium"
        ) from exc

    storage_path = Path(storage_state).expanduser() if storage_state else None
    if storage_path:
        storage_path.parent.mkdir(parents=True, exist_ok=True)

    download_root = Path(downloads_dir).expanduser() if downloads_dir else None
    if download_root:
        download_root.mkdir(parents=True, exist_ok=True)

    max_unique_searches = max(8, min(28, max_messages + 10))
    max_rows_per_search = max(8, min(24, max_messages * 2))

    def _launch_and_run(use_storage: bool) -> list[Dict[str, Any]]:
        _candidates: list[Dict[str, Any]] = []
        _seen: set[str] = set()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            ctx_kwargs: dict[str, Any] = {"accept_downloads": bool(download_root)}
            if use_storage and storage_path and storage_path.exists():
                ctx_kwargs["storage_state"] = str(storage_path)
                print(f"[VAMP-Outlook] Loading saved session from {storage_path}", flush=True)
            else:
                print("[VAMP-Outlook] Starting fresh login (no saved session)", flush=True)
            context = browser.new_context(**ctx_kwargs)
            page = context.new_page()
            page.goto(outlook_url, wait_until="domcontentloaded")
            _wait_for_outlook_mailbox(page)
            try:
                page.wait_for_timeout(1500)
            except Exception:
                pass

            # Persist session immediately after login so future runs are faster
            if storage_path:
                try:
                    context.storage_state(path=str(storage_path))
                    print(f"[VAMP-Outlook] Session saved to {storage_path}", flush=True)
                except Exception as _se:
                    print(f"[VAMP-Outlook] Could not save session: {_se}", flush=True)

            print(f"[VAMP-Outlook] Starting searches for {len(search_plans)} plans in {month_bucket}", flush=True)

            # Try to capture a live Graph API token from the Outlook Web session.
            # One Outlook (cloud.microsoft) calls graph.microsoft.com on every page load.
            graph_token: str | None = _intercept_graph_token(page)
            if graph_token:
                # Quick liveness check — /me returns user profile, very cheap
                import requests as _rq
                try:
                    _r = _rq.get(
                        "https://graph.microsoft.com/v1.0/me",
                        headers={"Authorization": f"Bearer {graph_token}"},
                        timeout=8,
                    )
                    if _r.status_code != 200:
                        print(f"[VAMP-Graph] Token check failed ({_r.status_code}) — falling back to browser scraping", flush=True)
                        graph_token = None
                    else:
                        print(f"[VAMP-Graph] Token valid — using Graph API for search", flush=True)
                except Exception as _te:
                    print(f"[VAMP-Graph] Token check error: {_te} — falling back", flush=True)
                    graph_token = None

            # Deduplicate plans by their computed search query
            _query_to_plans: dict[str, list[Dict[str, Any]]] = {}
            for plan in search_plans:
                queries = _search_queries_for_plan(plan, month_bucket=month_bucket, max_queries=10)
                if not queries:
                    print(f"[VAMP-Outlook] Skipping plan '{plan.get('title','')}' — empty query", flush=True)
                    continue
                for query in queries:
                    _query_to_plans.setdefault(query, []).append(plan)

            if len(_query_to_plans) > max_unique_searches:
                priority_queries = sorted(
                    _query_to_plans.items(),
                    key=lambda item: (
                        0 if any(ch.isdigit() for ch in item[0]) else 1,
                        len(item[1]),
                        len(item[0]),
                    ),
                )[:max_unique_searches]
                _query_to_plans = dict(priority_queries)

            print(f"[VAMP-Outlook] Deduplicated to {len(_query_to_plans)} unique searches", flush=True)

            # ----------------------------------------------------------------
            # PRIMARY PATH — Microsoft Graph API (no browser DOM scraping)
            # ----------------------------------------------------------------
            if graph_token:
                if include_calendar_events:
                    events = _graph_calendar_view_events(
                        graph_token,
                        month_bucket,
                        max_results=max_messages * 4,
                    )
                    for event in events:
                        if len(_candidates) >= max_messages:
                            break
                        combined_text, attachment_names, start_date = _event_text_for_matching(event)
                        if start_date and not _received_in_month(start_date, month_bucket):
                            continue
                        task_ids, kpa_hint_code, search_reason, matched = _match_candidate_to_plans(
                            month_bucket=month_bucket,
                            candidate_text=combined_text,
                            attachment_names=attachment_names,
                            received_at=start_date,
                            plans=list(search_plans),
                        )
                        if not task_ids:
                            continue

                        event_id = event.get("id") or ""
                        event_hash = hashlib.sha1(
                            "||".join(
                                [
                                    event_id,
                                    event.get("subject") or "",
                                    ((event.get("start") or {}).get("dateTime") or ""),
                                    combined_text[:1000],
                                ]
                            ).encode("utf-8", errors="ignore")
                        ).hexdigest()[:16]
                        if event_hash in _seen:
                            continue
                        _seen.add(event_hash)

                        _kpa_folder = kpa_hint_code or "CALENDAR"
                        body_artifact_path = ""
                        if download_root:
                            target_dir = download_root / month_bucket / _kpa_folder / event_hash
                            body_artifact_path = _calendar_event_artifact(event, target_dir)

                        if search_reason:
                            search_reason = f"calendar event → {search_reason}"
                        source_context = _source_context(combined_text, source="outlook_calendar")

                        _candidates.append(
                            {
                                "source": "outlook_calendar",
                                "source_message_id": event_id or event_hash,
                                "source_url": event.get("webLink") or "",
                                "month_bucket": month_bucket,
                                "subject": event.get("subject") or "",
                                "sender": "Calendar",
                                "recipients": "",
                                "received_at": start_date,
                                "body_text": combined_text[:4000],
                                "attachment_names": attachment_names,
                                "attachment_paths": [],
                                "body_artifact_path": body_artifact_path,
                                "task_candidates": task_ids,
                                "matched_tasks": matched,
                                "kpa_hint_code": kpa_hint_code,
                                "evidence_type_hint": "calendar_appointment",
                                "search_reason": search_reason,
                                "source_context": source_context,
                                "meta": {
                                    "calendar_event_id": event_id,
                                    "start": event.get("start"),
                                    "end": event.get("end"),
                                    "response_status": event.get("responseStatus"),
                                    "organizer": event.get("organizer"),
                                },
                            }
                        )

                for query, matching_plans in _query_to_plans.items():
                    print(f"[VAMP-Graph] Searching: {query}", flush=True)
                    messages = _graph_search_messages(
                        graph_token, query, max_results=max_messages * 2
                    )
                    active_plan: Dict[str, Any] | None = (
                        matching_plans[0] if matching_plans else None
                    )
                    for msg in messages:
                        msg_id: str = msg.get("id", "")
                        subject: str = msg.get("subject") or ""
                        from_obj = msg.get("from", {}).get("emailAddress", {})
                        sender: str = (
                            f"{from_obj.get('name', '')} <{from_obj.get('address', '')}>".strip()
                        )
                        received_at: str = msg.get("receivedDateTime") or ""
                        body_obj = msg.get("body", {})
                        body_raw: str = body_obj.get("content") or ""
                        if body_obj.get("contentType") == "html":
                            body_text: str = re.sub(
                                r"\s+", " ", re.sub(r"<[^>]+>", " ", body_raw)
                            ).strip()
                        else:
                            body_text = body_raw.strip()

                        attachment_names: list[str] = []
                        attachment_objs: list[Dict[str, Any]] = []
                        if msg.get("hasAttachments") and msg_id:
                            attachment_objs = _graph_get_attachments(graph_token, msg_id)
                            attachment_names = [a.get("name", "") for a in attachment_objs]

                        combined_text = " ".join(
                            filter(None, [subject, sender, received_at, body_text])
                        )
                        task_ids, kpa_hint_code, search_reason, matched = (
                            _match_candidate_to_plans(
                                month_bucket=month_bucket,
                                candidate_text=combined_text,
                                attachment_names=attachment_names,
                                received_at=received_at,
                                plans=matching_plans if matching_plans else list(search_plans),
                            )
                        )

                        has_evidence_payload = bool(
                            attachment_names
                            or (include_body_only_candidates and body_text)
                        )
                        if not task_ids or not has_evidence_payload:
                            continue

                        message_hash = hashlib.sha1(
                            "||".join(
                                [subject, sender, received_at, body_text[:1000]]
                            ).encode("utf-8", errors="ignore")
                        ).hexdigest()[:16]
                        if message_hash in _seen:
                            continue
                        _seen.add(message_hash)

                        _kpa_folder = (
                            kpa_hint_code
                            or (active_plan.get("kpa_code") if active_plan else None)
                            or "UNKNOWN"
                        )
                        attachment_paths: list[str] = []
                        if download_root and attachment_objs and msg_id:
                            target_dir = (
                                download_root / month_bucket / _kpa_folder / message_hash
                            )
                            for att in attachment_objs:
                                att_name = att.get("name", "attachment")
                                att_path = target_dir / att_name
                                if _graph_download_attachment(
                                    graph_token, msg_id, att["id"], att_path
                                ):
                                    attachment_paths.append(str(att_path))

                        body_artifact_path = ""
                        if not attachment_paths and body_text and download_root:
                            target_dir = (
                                download_root / month_bucket / _kpa_folder / message_hash
                            )
                            target_dir.mkdir(parents=True, exist_ok=True)
                            body_file = target_dir / f"{_safe_fragment(subject or 'message')}.txt"
                            body_file.write_text(
                                "\n".join(
                                    [
                                        f"Subject: {subject}",
                                        f"Sender: {sender}",
                                        f"Received: {received_at}",
                                        "",
                                        body_text,
                                    ]
                                ),
                                encoding="utf-8",
                            )
                            body_artifact_path = str(body_file)

                        if search_reason:
                            search_reason = f"graph '{query}' → {search_reason}"
                        source_context = _source_context(
                            " ".join([subject, sender, received_at, body_text, " ".join(attachment_names)]),
                            source="outlook_graph",
                        )

                        _candidates.append(
                            {
                                "source": "outlook_graph",
                                "source_message_id": msg_id or message_hash,
                                "source_url": f"https://outlook.cloud.microsoft/mail/id/{msg_id}",
                                "month_bucket": month_bucket,
                                "subject": subject,
                                "sender": sender,
                                "recipients": "",
                                "received_at": received_at,
                                "body_text": body_text[:4000],
                                "attachment_names": attachment_names,
                                "attachment_paths": attachment_paths,
                                "body_artifact_path": body_artifact_path,
                                "task_candidates": task_ids,
                                "matched_tasks": matched,
                                "kpa_hint_code": kpa_hint_code,
                                "evidence_type_hint": (
                                    attachment_names[0] if attachment_names else "outlook_message"
                                ),
                                "search_reason": search_reason,
                                "source_context": source_context,
                                "meta": {
                                    "graph_message_id": msg_id,
                                    "search_query": query,
                                    "active_task_id": (
                                        active_plan.get("task_id") if active_plan else None
                                    ),
                                },
                            }
                        )
                        if len(_candidates) >= max_messages:
                            break
                    if len(_candidates) >= max_messages:
                        break
                # end Graph API search loop

            # ----------------------------------------------------------------
            # FALLBACK PATH — browser DOM scraping (used only when Graph token
            # could not be obtained from the live session)
            # ----------------------------------------------------------------
            else:
                print("[VAMP-Outlook] No Graph token — using browser DOM scraping", flush=True)
                # Re-wait for the mailbox UI — _intercept_graph_token reloads the
                # page, so the search box may not be ready immediately after.
                _wait_for_outlook_mailbox(page)
                # Build work items: [(query_or_None, matching_plans), ...].
                # query=None means no search — process whatever rows are visible.
                searched_any_plan = False
                _work_items: list[tuple] = list(_query_to_plans.items()) or [(None, list(search_plans) or [])]

                for _query, matching_plans in _work_items:
                    if len(_candidates) >= max_messages:
                        break
                    if _query is not None:
                        print(f"[VAMP-Outlook] Searching: {_query}", flush=True)
                        if not _run_outlook_search(page, _query):
                            print(f"[VAMP-Outlook] Search failed for query: {_query}", flush=True)
                            continue
                        searched_any_plan = True
                    # Process rows immediately while search results are still visible.
                    rows = _collect_row_candidates(page)
                    print(f"[VAMP-Outlook] Found {len(rows)} rows for {len(matching_plans)} plans", flush=True)
                    active_plan = matching_plans[0] if matching_plans else None
                    for row in rows[:max_rows_per_search]:
                        if len(_candidates) >= max_messages:
                            break
                        try:
                            row_text = _normalize_text(row.inner_text(timeout=600))
                        except Exception:
                            row_text = ""
                        # Pre-filter: if row text contains a date outside the target month, skip.
                        _row_date = _extract_row_date_from_text(row_text, month_bucket)
                        _row_plans = matching_plans if matching_plans else list(search_plans)
                        if _row_date and not any(
                            _received_in_plan_window(_row_date, month_bucket, plan)
                            for plan in _row_plans
                        ):
                            print(f"[VAMP-Outlook] Skip row (date {_row_date} outside {month_bucket})", flush=True)
                            continue
                        guessed_subject, guessed_sender = _guess_row_fields(row_text)

                        if matching_plans:
                            row_task_ids, _row_kpa, _row_reason, row_matched = _match_candidate_to_plans(
                                month_bucket=month_bucket,
                                candidate_text=row_text,
                                attachment_names=[],
                                received_at=_row_date or "",
                                plans=matching_plans,
                            )
                            if not row_task_ids:
                                preview = row_text[:120].replace("\n", " ")
                                print(
                                    f"[VAMP-Outlook] Skip row before open (no plan match): {preview}",
                                    flush=True,
                                )
                                continue
                            print(
                                f"[VAMP-Outlook] Opening matched row: {row_matched[0].get('title', '') if row_matched else ''}",
                                flush=True,
                            )

                        try:
                            row.click(timeout=3000)
                        except Exception:
                            continue
                        try:
                            page.wait_for_timeout(800)
                        except Exception:
                            pass

                        subject = _first_non_empty_text(
                            page,
                            [
                                "div[role='main'] h1",
                                "div[role='main'] [data-testid='message-subject']",
                                "div[role='heading'][aria-level='1']",
                            ],
                        ) or guessed_subject
                        sender = _first_non_empty_text(
                            page,
                            [
                                "div[role='main'] [data-testid='message-from']",
                                "div[role='main'] [aria-label^='From']",
                                "div[role='main'] span[title*='@']",
                            ],
                        ) or guessed_sender
                        recipients = _first_non_empty_text(
                            page,
                            [
                                "div[role='main'] [aria-label^='To']",
                                "div[role='main'] [data-testid='message-to']",
                            ],
                        )
                        received_at = _first_non_empty_attr(
                            page,
                            [
                                ("div[role='main'] time", "datetime"),
                                ("div[role='main'] [data-testid='message-date'] time", "datetime"),
                            ],
                        ) or _first_non_empty_text(
                            page,
                            [
                                "div[role='main'] time",
                                "div[role='main'] [data-testid='message-date']",
                                "div[role='main'] [aria-label*='Received']",
                            ],
                        )
                        # Fallback: extract date from row_text (One Outlook embeds MM/DD/YYYY)
                        if not received_at:
                            received_at = _extract_date_from_text(row_text)
                        body_text = _first_non_empty_text(
                            page,
                            [
                                "div[role='main'] div[aria-label='Message body']",
                                "div[role='main'] [data-testid='message-body']",
                                "div[role='document']",
                            ],
                        )
                        attachment_names = _collect_attachment_names(page)

                        combined_text = " ".join(
                            part
                            for part in [subject, sender, recipients, received_at, body_text, row_text]
                            if part
                        )
                        plans_to_match = matching_plans if matching_plans else list(search_plans)
                        task_ids, kpa_hint_code, search_reason, matched = _match_candidate_to_plans(
                            month_bucket=month_bucket,
                            candidate_text=combined_text,
                            attachment_names=attachment_names,
                            received_at=received_at,
                            plans=plans_to_match,
                        )

                        has_evidence_payload = bool(
                            attachment_names or (include_body_only_candidates and body_text)
                        )
                        if not task_ids or not has_evidence_payload:
                            continue

                        message_hash = hashlib.sha1(
                            "||".join([subject, sender, received_at, body_text[:1000], page.url]).encode(
                                "utf-8", errors="ignore"
                            )
                        ).hexdigest()[:16]
                        if message_hash in _seen:
                            continue
                        _seen.add(message_hash)

                        attachment_paths = []
                        _kpa_folder = (
                            kpa_hint_code
                            or (active_plan.get("kpa_code") if active_plan else None)
                            or "UNKNOWN"
                        )
                        if download_root:
                            target_dir = download_root / month_bucket / _kpa_folder / message_hash
                            downloaded = _download_visible_attachments(page, target_dir)
                            attachment_paths = [str(target_dir / name) for name in downloaded]
                            for name in downloaded:
                                if name not in attachment_names:
                                    attachment_names.append(name)

                        body_artifact_path = ""
                        if not attachment_paths and body_text and download_root:
                            target_dir = download_root / month_bucket / _kpa_folder / message_hash
                            target_dir.mkdir(parents=True, exist_ok=True)
                            body_file = target_dir / f"{_safe_fragment(subject or 'message')}.txt"
                            body_file.write_text(
                                "\n".join(
                                    [
                                        f"Subject: {subject}",
                                        f"Sender: {sender}",
                                        f"Recipients: {recipients}",
                                        f"Received: {received_at}",
                                        "",
                                        body_text,
                                    ]
                                ),
                                encoding="utf-8",
                            )
                            body_artifact_path = str(body_file)

                        if matching_plans and search_reason:
                            search_reason = f"search '{_search_query_for_plan(matching_plans[0], month_bucket=month_bucket)}' -> {search_reason}"
                        source_context = _source_context(
                            " ".join([subject, sender, recipients, received_at, body_text, row_text, " ".join(attachment_names)]),
                            source="outlook_playwright",
                        )

                        _candidates.append(
                            {
                                "source": "outlook_playwright",
                                "source_message_id": message_hash,
                                "source_url": page.url,
                                "month_bucket": month_bucket,
                                "subject": subject,
                                "sender": sender,
                                "recipients": recipients,
                                "received_at": received_at,
                                "body_text": body_text,
                                "attachment_names": attachment_names,
                                "attachment_paths": attachment_paths,
                                "body_artifact_path": body_artifact_path,
                                "task_candidates": task_ids,
                                "matched_tasks": matched,
                                "kpa_hint_code": kpa_hint_code,
                                "evidence_type_hint": (
                                    attachment_names[0] if attachment_names else "outlook_message"
                                ),
                                "search_reason": search_reason,
                                "source_context": source_context,
                                "meta": {
                                    "row_preview": row_text[:300],
                                    "outlook_url": page.url,
                                    "active_task_id": active_plan.get("task_id") if active_plan else None,
                                    "search_query": (
                                        _search_query_for_plan(active_plan, month_bucket=month_bucket)
                                        if active_plan
                                        else ""
                                    ),
                                },
                            }
                        )
                        print(f"[VAMP-Outlook] Candidate added: {subject[:60]!r}", flush=True)
                    # end row loop
                # end work items loop

                if searched_any_plan:
                    _clear_outlook_search(page, outlook_url)


            # Final session save
            if storage_path:
                try:
                    context.storage_state(path=str(storage_path))
                except Exception:
                    pass
            context.close()
            browser.close()
        return _candidates

    # Try with saved session first; if the page closes immediately (expired session),
    # wipe the state file and retry with a fresh login.
    try:
        return _launch_and_run(use_storage=True)
    except Exception as exc:
        if storage_path and storage_path.exists() and (
            "TargetClosedError" in type(exc).__name__ or "closed" in str(exc).lower()
        ):
            print(f"[VAMP-Outlook] Session expired or invalid — clearing state and retrying with fresh login.", flush=True)
            try:
                storage_path.unlink()
            except Exception:
                pass
            return _launch_and_run(use_storage=False)
        raise
