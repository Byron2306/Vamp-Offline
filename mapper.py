
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

try:
    from .progress_store import ProgressStore, TaskRow
    from .task_map import default_tasks_for_year, tasks_from_expectations
except ImportError:
    from progress_store import ProgressStore, TaskRow
    from task_map import default_tasks_for_year, tasks_from_expectations


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
    # Clear existing tasks for this staff/year to prevent duplication
    try:
        deleted = store.clear_tasks_for_staff_year(staff_id, int(year))
        if deleted > 0:
            print(f"Cleared {deleted} existing tasks for staff {staff_id} year {year}")
    except Exception as e:
        print(f"Warning: could not clear existing tasks: {e}")
    
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
    max_links: int = 3,
) -> List[Dict[str, Any]]:
    """Create evidence_task links for evidence_id; return mapped task summaries.

    Robust + conservative mapping:
    - Filter candidates by month (+ KPA when available).
    - Score by token overlap between evidence signal and task(title+hints).
    - Link only the top-N above a threshold (avoids mapping every task).
    - Safe fallbacks when classification is weak.
    """
    month = _parse_month(month_bucket)
    if not month:
        return []

    kpa_code_norm = str(kpa_code or "").strip()
    task_rows = store.list_tasks_for_window(int(year), [month], kpa_code=(kpa_code_norm or None))
    if not task_rows and not kpa_code_norm:
        task_rows = store.list_tasks_for_window(int(year), [month], kpa_code=None)
    if not task_rows:
        return []

    signal = _text_signal(meta)
    signal_tokens = set(re.findall(r"[a-z0-9]{3,}", signal))

    def _tokens_for_task(row: Dict[str, Any]) -> Tuple[set[str], List[str]]:
        try:
            hints_payload = json.loads(row.get("hints_json") or "{}")
        except Exception:
            hints_payload = {}
        hints = hints_payload.get("hints") or []
        hint_terms = [str(h).strip().lower() for h in hints if str(h).strip()]
        blob = " ".join([row.get("title") or ""] + hint_terms)
        return set(re.findall(r"[a-z0-9]{3,}", blob.lower())), hint_terms

    scored: List[Tuple[float, Dict[str, Any], int, int]] = []
    for t in task_rows:
        try:
            row = dict(t)
            task_tokens, hint_terms = _tokens_for_task(row)
            if not task_tokens:
                continue

            overlap = signal_tokens.intersection(task_tokens)
            overlap_ratio = len(overlap) / max(1, len(task_tokens))

            hint_hits = 0
            for term in hint_terms:
                if term and term in signal:
                    hint_hits += 1

            base = 0.30 if kpa_code_norm else 0.15
            conf = base + 0.55 * overlap_ratio + min(0.30, 0.10 * hint_hits)
            scored.append((float(conf), row, hint_hits, len(overlap)))
        except Exception:
            continue

    scored.sort(key=lambda x: (x[0], x[2], x[3]), reverse=True)
    threshold = 0.35 if kpa_code_norm else 0.45

    mapped: List[Dict[str, Any]] = []
    for conf, row, _, _ in scored[: max_links * 2]:
        if len(mapped) >= max_links:
            break
        if conf < threshold:
            continue
        try:
            conf = float(min(conf, 0.95))
            store.upsert_mapping(evidence_id, row["task_id"], mapped_by=mapped_by, confidence=conf)
            mapped.append(
                {"task_id": row["task_id"], "kpa_code": row["kpa_code"], "title": row["title"], "confidence": conf}
            )
        except Exception:
            continue

    if not mapped and kpa_code_norm:
        # Safe fallback: map to first task in month/KPA (single link only).
        try:
            pick = dict(task_rows[0])
            store.upsert_mapping(evidence_id, pick["task_id"], mapped_by=mapped_by + ":fallback", confidence=0.35)
            mapped.append(
                {"task_id": pick["task_id"], "kpa_code": pick["kpa_code"], "title": pick["title"], "confidence": 0.35}
            )
        except Exception:
            pass

    if not mapped and not kpa_code_norm:
        # Conservative fallback: one KPA1 mapping.
        try:
            all_rows = store.list_tasks_for_window(int(year), [month], kpa_code=None)
            pick = None
            for r in all_rows:
                if str(r.get("kpa_code") or "") == "KPA1":
                    pick = r
                    break
            if pick is None and all_rows:
                pick = all_rows[0]
            if pick is not None:
                pick_d = dict(pick)
                store.upsert_mapping(evidence_id, pick_d["task_id"], mapped_by=mapped_by + ":fallback", confidence=0.25)
                mapped.append(
                    {"task_id": pick_d["task_id"], "kpa_code": pick_d["kpa_code"], "title": pick_d["title"], "confidence": 0.25}
                )
        except Exception:
            pass

    return mapped


def new_evidence_id() -> str:
    return uuid.uuid4().hex
