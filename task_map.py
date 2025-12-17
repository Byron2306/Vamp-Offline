
from __future__ import annotations

"""
Fallback default task catalog per KPA/month when TA/PA expectations are not available.

This is intentionally conservative and generic; it ensures progress mapping still works.
If expectations exist (expectation_engine.build_staff_expectations), those will override.
"""

import hashlib
import json
from typing import Any, Dict, List

from .progress_store import TaskRow, _month_range


def _hid(*parts: str) -> str:
    return hashlib.sha1("::".join(parts).encode("utf-8")).hexdigest()[:14]


def default_tasks_for_year(staff_id: str, year: int) -> List[TaskRow]:
    """Create a minimal-but-robust task set for all KPAs across the year."""
    tasks: List[TaskRow] = []

    def add(kpa: str, month: int, title: str, cadence: str, min_req: int, stretch: int, lead_lag: str, hints: List[str]) -> None:
        ws, we = _month_range(year, month)
        task_id = _hid(staff_id, str(year), kpa, title, f"{month:02d}")
        tasks.append(
            TaskRow(
                task_id=task_id,
                kpa_code=kpa,
                title=title,
                window_start=ws,
                window_end=we,
                cadence=cadence,
                min_required=min_req,
                stretch_target=stretch,
                lead_lag=lead_lag,
                hints_json=json.dumps({"hints": hints, "source": "defaults"}, ensure_ascii=False),
            )
        )

    # Generic monthly evidence tasks
    for m in range(1, 13):
        add("KPA1", m, "Teaching delivery evidence (classes/lesson plan/LMS activity)", "monthly", 1, 2, "lead",
            ["efundi", "lecture", "class", "assessment", "lms", "tutorial"])
        add("KPA2", m, "Research/Writing progress artefact (draft/log/submission)", "monthly", 1, 2, "lead",
            ["draft", "manuscript", "proposal", "ethics", "submission", "review"])
        add("KPA3", m, "Academic leadership artefact (committee/meeting/minutes)", "monthly", 1, 2, "lead",
            ["minutes", "committee", "meeting", "chair", "agenda"])
        add("KPA4", m, "Social responsiveness/engagement artefact", "monthly", 0, 1, "lead",
            ["community", "engagement", "outreach", "school", "workshop"])
        # OHS is low weight; we expect occasional evidence
        if m in (2, 6, 9, 11):
            add("KPA5", m, "OHS/Compliance check artefact (training, inspections, DALRO/POPIA)", "per_quarter", 1, 1, "lag",
                ["ohs", "safety", "compliance", "popia", "dalro", "risk"])

    # Semester milestones (lag-like)
    add("KPA1", 6, "Marks submission / semester assessment completion", "milestone", 1, 1, "lag",
        ["marks", "gradebook", "exam", "assessment submitted"])
    add("KPA1", 11, "Year-end marks and moderation completion", "milestone", 1, 1, "lag",
        ["moderation", "final marks", "exam board"])

    add("KPA2", 6, "Midyear research milestone (submission/ethics/grant)", "milestone", 0, 1, "lag",
        ["ethics", "grant", "submission", "accepted"])
    add("KPA2", 11, "Year-end research milestone (acceptance/publication)", "milestone", 0, 1, "lag",
        ["acceptance", "published", "doi", "journal"])

    return tasks


def tasks_from_expectations(staff_id: str, year: int, expectations: Dict[str, Any]) -> List[TaskRow]:
    """Convert expectation_engine output into expanded per-month TaskRow entries."""
    tasks: List[TaskRow] = []
    lead_lag_map = (expectations or {}).get("lead_lag", {}) or {}

    raw_tasks = (expectations or {}).get("tasks") or []
    for t in raw_tasks:
        try:
            kpa = str(t.get("kpa_code") or "").strip() or "KPA1"
            title = str(t.get("title") or "").strip() or "Expectation task"
            cadence = str(t.get("cadence") or "monthly").strip()
            months = t.get("months") or []
            min_req = int(t.get("minimum_count") or 0)
            stretch = int(t.get("stretch_count") or min_req)
            hints = t.get("evidence_hints") or []
            lead_lag = "lead"
            ll = lead_lag_map.get(kpa) or {}
            lead_lag_payload = {"lead": ll.get("lead", ""), "lag": ll.get("lag", "")}

            if not isinstance(months, list) or not months:
                months = list(range(1, 13))

            for m in months:
                try:
                    m_int = int(m)
                except Exception:
                    continue
                ws, we = _month_range(year, m_int)
                base_id = str(t.get("id") or "")
                task_id = _hid(staff_id, str(year), base_id, f"{m_int:02d}")
                tasks.append(
                    TaskRow(
                        task_id=task_id,
                        kpa_code=kpa,
                        title=title,
                        window_start=ws,
                        window_end=we,
                        cadence=cadence,
                        min_required=min_req,
                        stretch_target=stretch,
                        lead_lag=lead_lag,
                        hints_json=json.dumps({"hints": hints, "source": "expectations", "lead_lag": lead_lag_payload}, ensure_ascii=False),
                    )
                )
        except Exception:
            continue

    return tasks
