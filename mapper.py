
from __future__ import annotations

"""
Evidence -> task mapping rules.

This module is deliberately conservative:
- It always maps evidence to at least "its KPA/month" tasks when possible.
- It boosts confidence when filename/evidence_type/snippet matches task hints.
"""

import json
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from .progress_store import ProgressStore, TaskRow
from .task_map import default_tasks_for_year, tasks_from_expectations


def _parse_month(month_bucket: str) -> Optional[int]:
    # month_bucket is expected like "2025-03" or "2025-03_MAR"
    m = re.search(r"(\d{4})-(\d{2})", str(month_bucket))
    if not m:
        return None
    try:
        return int(m.group(2))
    except Exception:
        return None


def ensure_tasks(
    store: ProgressStore,
    *,
    staff_id: str,
    year: int,
    expectations: Optional[Dict[str, Any]] = None,
) -> int:
    """Ensure a staff/year task catalog exists in sqlite; return count inserted."""
    if expectations:
        rows = tasks_from_expectations(staff_id, int(year), expectations)
        if rows:
            return store.upsert_tasks(rows)
    # fallback
    return store.upsert_tasks(default_tasks_for_year(staff_id, int(year)))


def _text_signal(meta: Dict[str, Any]) -> str:
    parts: List[str] = []
    for key in ("filename", "file_name", "evidence_type", "impact_summary", "snippet", "evidence_snippet", "summary"):
        v = meta.get(key)
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())
    # also include ctx subfields if present
    ctx = meta.get("ctx")
    if isinstance(ctx, dict):
        for key in ("evidence_type", "impact_summary", "summary", "evidence_snippet", "filename"):
            v = ctx.get(key)
            if isinstance(v, str) and v.strip():
                parts.append(v.strip())
    return " ".join(parts).lower()


def map_evidence_to_tasks(
    store: ProgressStore,
    *,
    evidence_id: str,
    staff_id: str,
    year: int,
    month_bucket: str,
    kpa_code: str,
    meta: Dict[str, Any],
    mapped_by: str = "rules:v1",
) -> List[Dict[str, Any]]:
    """Create evidence_task links for evidence_id; return mapped task summaries."""
    month = _parse_month(month_bucket)
    if not month:
        return []

    # Candidate tasks: tasks expanded per-month -> window_start prefix matches.
    # If kpa_code is missing/blank, fall back to all-KPA candidates for the month
    # and map based on hint matches (robust behaviour when classification is uncertain).
    kpa_code_norm = str(kpa_code or "").strip()
    task_rows = store.list_tasks_for_window(
        int(year),
        [month],
        kpa_code=(kpa_code_norm or None),
    )
    if not task_rows and not kpa_code_norm:
        task_rows = store.list_tasks_for_window(int(year), [month], kpa_code=None)
    signal = _text_signal(meta)

    mapped: List[Dict[str, Any]] = []
    # First pass: map by hints (or by month/KPA default mapping).
    for t in task_rows:
        try:
            hints_payload = {}
            try:
                hints_payload = json.loads(t["hints_json"] or "{}")
            except Exception:
                hints_payload = {}
            hints = hints_payload.get("hints") or []
            # Base confidence depends on whether KPA was known.
            conf = 0.35 if kpa_code_norm else 0.20
            if hints and isinstance(hints, list):
                hits = 0
                for h in hints:
                    hs = str(h).strip().lower()
                    if hs and hs in signal:
                        hits += 1
                if hits:
                    conf = min(0.95, 0.35 + 0.15 * hits)
                else:
                    # If KPA is known, keep a low-but-present mapping to the month/KPA task.
                    # If KPA is unknown, avoid spamming mappings without signals.
                    conf = 0.45 if kpa_code_norm else 0.0

            if conf <= 0.0:
                continue

            store.upsert_mapping(evidence_id, t["task_id"], mapped_by=mapped_by, confidence=float(conf))
            mapped.append(
                {
                    "task_id": t["task_id"],
                    "kpa_code": t["kpa_code"],
                    "title": t["title"],
                    "confidence": float(conf),
                }
            )
        except Exception:
            continue

    # If KPA is unknown and no mappings were produced (e.g., no hint hits),
    # create a single conservative fallback mapping to the generic KPA1 monthly task.
    if not mapped and not kpa_code_norm:
        try:
            all_rows = store.list_tasks_for_window(int(year), [month], kpa_code=None)
            # Prefer KPA1 first, else take the first task in the month.
            pick = None
            for r in all_rows:
                if str(r.get("kpa_code") or "") == "KPA1":
                    pick = r
                    break
            if pick is None and all_rows:
                pick = all_rows[0]
            if pick is not None:
                store.upsert_mapping(evidence_id, pick["task_id"], mapped_by=mapped_by + ":fallback", confidence=0.25)
                mapped.append(
                    {
                        "task_id": pick["task_id"],
                        "kpa_code": pick["kpa_code"],
                        "title": pick["title"],
                        "confidence": 0.25,
                    }
                )
        except Exception:
            pass

    return mapped


def new_evidence_id() -> str:
    return uuid.uuid4().hex
