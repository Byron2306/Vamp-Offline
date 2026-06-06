
from __future__ import annotations

"""
Evidence -> task mapping rules.

This module is deliberately conservative:
- It maps evidence only when there is a concrete task signal.
- It boosts confidence when filename/evidence_type/snippet matches task hints.
"""

import json
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

_GENERIC_TASK_TOKENS = {
    "academic", "agenda", "and", "assessment", "committee", "data", "education",
    "evidence", "faculty", "meeting", "minutes", "module", "performance",
    "project", "progress", "report", "research", "school", "staff", "student",
    "task", "teaching", "the", "with", "work",
}


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


def _recover_metadata_mappings(store: ProgressStore, staff_id: str, year: int, current_task_rows: List[Dict[str, Any]]) -> int:
    """Recover non-manual collector mappings after task-id regeneration.

    Automatic mappings are not stored as human assertions. When the task catalog is
    rebuilt, SQLite cascades old edges away, so we recreate only links that can be
    tied back to a current task by exact stored title or direct module-code match.
    """
    by_id = {str(r.get("task_id")): r for r in current_task_rows if r.get("task_id")}
    by_month_kpa_title = {
        (
            str(r.get("window_start") or "")[:7],
            str(r.get("kpa_code") or ""),
            str(r.get("title") or "").strip().lower(),
        ): r
        for r in current_task_rows
    }

    recovered = 0
    try:
        evidence_rows = [dict(row) for row in store.list_evidence(staff_id, int(year))]
    except Exception:
        return 0

    for ev in evidence_rows:
        evidence_id = str(ev.get("evidence_id") or "")
        if not evidence_id:
            continue
        try:
            if store.list_mappings_for_evidence(evidence_id):
                continue
        except Exception:
            pass

        try:
            meta = json.loads(ev.get("meta_json") or "{}")
        except Exception:
            meta = {}
        month = str(ev.get("month_bucket") or "")[:7]
        ev_kpa = str(ev.get("kpa_code") or "")

        target = None
        outlook = meta.get("outlook") if isinstance(meta.get("outlook"), dict) else {}
        efundi = meta.get("efundi") if isinstance(meta.get("efundi"), dict) else {}

        if outlook:
            for match in outlook.get("matched_tasks") or []:
                if not isinstance(match, dict):
                    continue
                quality = match.get("match_quality") if isinstance(match.get("match_quality"), dict) else {}
                strong_signals: List[str] = []
                for key in ("module_hits", "evidence_hits", "attachment_hits", "phrase_hits"):
                    strong_signals.extend([str(v).lower() for v in (quality.get(key) or []) if str(v).strip()])
                terms = [str(t).lower() for t in (match.get("matched_terms") or []) if str(t).strip()]
                score = float(match.get("score") or 0.0)
                if not strong_signals and (not terms or all(t in _GENERIC_TASK_TOKENS for t in terms)):
                    continue
                if not strong_signals and score < 4.0:
                    continue
                title = str(match.get("title") or "").strip().lower()
                candidate = by_month_kpa_title.get((month, ev_kpa, title))
                if candidate:
                    if ev_kpa == "KPA2":
                        blob = json.dumps(meta).lower()
                        if not any(term in blob for term in ("ohs", "safety", "compliance", "declaration", "popia", "dalro")):
                            continue
                    target = candidate
                    break
        elif efundi:
            module_code = str(efundi.get("module_code") or "").replace(" ", "").lower()
            for row in current_task_rows:
                if str(row.get("window_start") or "")[:7] != month:
                    continue
                if str(row.get("kpa_code") or "") != ev_kpa:
                    continue
                title = str(row.get("title") or "").replace(" ", "").lower()
                if module_code and module_code in title:
                    target = row
                    break
            if target is None:
                target_id = str(meta.get("target_task_id") or "")
                candidate = by_id.get(target_id)
                if candidate and str(candidate.get("window_start") or "")[:7] == month and str(candidate.get("kpa_code") or "") == ev_kpa:
                    target = candidate

        if not target:
            continue
        try:
            mapped_by = "efundi_collect:direct_lms" if efundi else "outlook_collect:targeted"
            confidence = 0.98 if efundi else 0.9
            store.upsert_mapping(evidence_id, target["task_id"], mapped_by=mapped_by, confidence=confidence)
            recovered += 1
        except Exception:
            continue
    return recovered


def ensure_tasks(
    store: ProgressStore,
    *,
    staff_id: str,
    year: int,
    expectations: Optional[Dict[str, Any]] = None,
) -> int:
    """Ensure a staff/year task catalog exists in sqlite; return count inserted."""
    # Preserve all evidence-task mappings for this staff/year. Task rebuilds
    # delete rows from tasks, and sqlite cascades that into evidence_task. Without
    # this, merely refreshing progress can make collected evidence stop counting.
    preserved_mappings: List[Tuple[str, str, str, float, str]] = []
    try:
        try:
            preserved_mappings = store.get_mappings_for_staff_year(staff_id, int(year))
        except Exception:
            preserved_mappings = []
        try:
            existing_keys = {(m[0], m[1]) for m in preserved_mappings if len(m) >= 2}
            asserted_rows = store.get_asserted_mappings_for_staff_year(staff_id, int(year))
            asserted_titles: Dict[Tuple[str, str], str] = {}
            try:
                con = store._connect()
                try:
                    ev_ids = [row[0] for row in asserted_rows if row and row[0]]
                    if ev_ids:
                        placeholders = ",".join(["?"] * len(ev_ids))
                        for ev in con.execute(
                            f"SELECT evidence_id, meta_json FROM evidence WHERE evidence_id IN ({placeholders})",
                            ev_ids,
                        ).fetchall():
                            try:
                                meta = json.loads(ev["meta_json"] or "{}")
                            except Exception:
                                meta = {}
                            target_task_id = meta.get("target_task_id") or ""
                            outlook = meta.get("outlook") if isinstance(meta.get("outlook"), dict) else {}
                            for match in outlook.get("matched_tasks") or []:
                                if not isinstance(match, dict):
                                    continue
                                task_id = match.get("task_id") or ""
                                title = match.get("title") or ""
                                if task_id and title:
                                    asserted_titles[(ev["evidence_id"], task_id)] = title
                            if target_task_id and meta.get("task"):
                                asserted_titles.setdefault((ev["evidence_id"], target_task_id), meta.get("task") or "")
                finally:
                    con.close()
            except Exception:
                asserted_titles = {}

            for evidence_id, task_id, mapped_by, confidence in asserted_rows:
                if (evidence_id, task_id) not in existing_keys:
                    preserved_mappings.append(
                        (
                            evidence_id,
                            task_id,
                            mapped_by,
                            float(confidence),
                            asserted_titles.get((evidence_id, task_id), ""),
                        )
                    )
        except Exception:
            pass

        # Only asserted/manual task rows are protected from deletion. Automatic
        # mappings are restored after rebuild when their task still exists, so
        # stale generated tasks do not accumulate.
        preserve_task_ids = list(
            {
                m[1]
                for m in preserved_mappings
                if len(m) >= 4 and m[1] and "asserted" in str(m[2])
            }
        )
        try:
            deleted = store.clear_tasks_for_staff_year_preserve(staff_id, int(year), preserve_task_ids)
        except Exception:
            deleted = store.clear_tasks_for_staff_year(staff_id, int(year))

        if deleted > 0:
            print(f"Cleared {deleted} existing tasks for staff {staff_id} year {year}")
    except Exception as e:
        print(f"Warning: could not clear existing tasks: {e}")

    # Insert new task rows
    if expectations:
        rows = tasks_from_expectations(staff_id, int(year), expectations)
        if rows:
            inserted = store.upsert_tasks(rows)
        else:
            inserted = store.upsert_tasks(default_tasks_for_year(staff_id, int(year)))
    else:
        inserted = store.upsert_tasks(default_tasks_for_year(staff_id, int(year)))

    # Restore preserved mappings where the task still exists in the tasks table,
    # or relink by old title when deterministic task IDs changed.
    try:
        # Get current task ids and titles for the year
        current_task_rows = [
            dict(row) for row in store.list_tasks_for_window(int(year), list(range(1, 13)), kpa_code=None)
        ]
        current_task_ids = set([r["task_id"] for r in current_task_rows])
        # Helper: simple token overlap title matcher
        def _title_tokens(s: str) -> set:
            return set(re.findall(r"[a-z0-9]{3,}", (s or "").lower()))

        for entry in preserved_mappings:
            # preserved_mappings entries may be (evidence_id, task_id, mapped_by, confidence) or include title
            if len(entry) == 5:
                evidence_id, task_id, mapped_by, confidence, old_title = entry
            else:
                evidence_id, task_id, mapped_by, confidence = entry
                old_title = ""

            if task_id in current_task_ids:
                try:
                    store.upsert_mapping(evidence_id, task_id, mapped_by=mapped_by, confidence=confidence)
                    continue
                except Exception:
                    continue

            # Try to find a candidate by exact title match first
            candidate_id = None
            old_tokens = _title_tokens(old_title)
            if old_title:
                for r in current_task_rows:
                    if (r.get("title") or "").strip().lower() == old_title.strip().lower():
                        candidate_id = r["task_id"]
                        break

            # If no exact match, fallback to token overlap heuristic
            if not candidate_id and old_tokens:
                best = (0.0, None)
                for r in current_task_rows:
                    t_tokens = _title_tokens(r.get("title") or "")
                    if not t_tokens:
                        continue
                    overlap = len(old_tokens.intersection(t_tokens))
                    score = overlap / max(1, len(t_tokens))
                    if score > best[0]:
                        best = (score, r["task_id"]) 
                if best[0] >= 0.4:
                    candidate_id = best[1]

            if candidate_id:
                try:
                    store.upsert_mapping(evidence_id, candidate_id, mapped_by=mapped_by, confidence=confidence)
                except Exception:
                    continue
        recovered = _recover_metadata_mappings(store, staff_id, int(year), current_task_rows)
        if recovered:
            print(f"Recovered {recovered} collector mappings for staff {staff_id} year {year}")
    except Exception:
        pass

    return inserted


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
    signal_tokens = set(re.findall(r"[a-z0-9]{3,}", signal)) - _GENERIC_TASK_TOKENS

    def _tokens_for_task(row: Dict[str, Any]) -> Tuple[set[str], List[str]]:
        try:
            hints_payload = json.loads(row.get("hints_json") or "{}")
        except Exception:
            hints_payload = {}
        hints = hints_payload.get("hints") or []
        hint_terms = [str(h).strip().lower() for h in hints if str(h).strip()]
        blob = " ".join([row.get("title") or ""] + hint_terms)
        return set(re.findall(r"[a-z0-9]{3,}", blob.lower())) - _GENERIC_TASK_TOKENS, hint_terms

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

            if not overlap and not hint_hits:
                continue

            base = 0.18 if kpa_code_norm else 0.10
            conf = base + 0.60 * overlap_ratio + min(0.30, 0.10 * hint_hits)
            scored.append((float(conf), row, hint_hits, len(overlap)))
        except Exception:
            continue

    scored.sort(key=lambda x: (x[0], x[2], x[3]), reverse=True)
    threshold = 0.42 if kpa_code_norm else 0.52

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

    return mapped


def new_evidence_id() -> str:
    return uuid.uuid4().hex
