
from __future__ import annotations

"""
SQLite-backed progress store for Phase A (evidence -> task mapping).

Design goals:
- UI-agnostic (Tkinter/HTML both use it through controller/api)
- Append-only evidence logging (idempotent by sha1 + staff/year/month if needed)
- Deterministic task catalog per staff/year from:
  (1) TA/PA expectations (expectation_engine.build_staff_expectations output)
  (2) fallback default task map (backend.progress.task_map)
- Evidence -> task mapping edges with confidence + mapped_by tag

This store is intentionally "small and safe": it uses sqlite3 only.
"""

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent  # Root of project where progress_store.py is located
DATA_DIR = BASE_DIR / "backend" / "data"
PROGRESS_DIR = DATA_DIR / "progress"
PROGRESS_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_DB_PATH = PROGRESS_DIR / "progress.db"


def _utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _month_range(year: int, month: int) -> Tuple[str, str]:
    """Return ISO date start/end for a given month."""
    import calendar
    last = calendar.monthrange(year, month)[1]
    start = date(year, month, 1).isoformat()
    end = date(year, month, last).isoformat()
    return start, end


@dataclass(frozen=True)
class TaskRow:
    task_id: str
    kpa_code: str
    title: str
    window_start: str
    window_end: str
    cadence: str
    min_required: int
    stretch_target: int
    lead_lag: str
    hints_json: str


class ProgressStore:
    """Thread-safe, single-file sqlite progress store."""

    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self._lock = threading.RLock()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.db_path), check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA foreign_keys=ON;")
        return con

    def _ensure_schema(self) -> None:
        with self._lock:
            con = self._connect()
            try:
                con.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS tasks(
                        task_id TEXT PRIMARY KEY,
                        kpa_code TEXT NOT NULL,
                        title TEXT NOT NULL,
                        window_start TEXT NOT NULL,
                        window_end TEXT NOT NULL,
                        cadence TEXT NOT NULL,
                        min_required INTEGER NOT NULL,
                        stretch_target INTEGER NOT NULL,
                        lead_lag TEXT NOT NULL,
                        hints_json TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS evidence(
                        evidence_id TEXT PRIMARY KEY,
                        sha1 TEXT,
                        staff_id TEXT NOT NULL,
                        year INTEGER NOT NULL,
                        month_bucket TEXT NOT NULL,
                        kpa_code TEXT,
                        rating TEXT,
                        tier TEXT,
                        file_path TEXT NOT NULL,
                        meta_json TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS evidence_task(
                        evidence_id TEXT NOT NULL,
                        task_id TEXT NOT NULL,
                        mapped_by TEXT NOT NULL,
                        confidence REAL NOT NULL,
                        created_at TEXT NOT NULL,
                        PRIMARY KEY (evidence_id, task_id),
                        FOREIGN KEY (evidence_id) REFERENCES evidence(evidence_id) ON DELETE CASCADE,
                        FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
                    );

                    CREATE INDEX IF NOT EXISTS idx_evidence_staff_year ON evidence(staff_id, year);
                    CREATE INDEX IF NOT EXISTS idx_evidence_month ON evidence(month_bucket);
                    CREATE INDEX IF NOT EXISTS idx_tasks_kpa ON tasks(kpa_code);
                    
                    CREATE TABLE IF NOT EXISTS asserted_mappings(
                        evidence_id TEXT NOT NULL,
                        task_id TEXT NOT NULL,
                        mapped_by TEXT NOT NULL,
                        confidence REAL NOT NULL,
                        staff_id TEXT,
                        year INTEGER,
                        created_at TEXT NOT NULL,
                        PRIMARY KEY (evidence_id, task_id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_asserted_staff_year ON asserted_mappings(staff_id, year);
                    """
                )
                con.commit()
            finally:
                con.close()

    # ----------------------------
    # Task management
    # ----------------------------
    def clear_tasks_for_staff_year(self, staff_id: str, year: int) -> int:
        """Delete all tasks for a specific staff/year (based on window_start year)."""
        with self._lock:
            con = self._connect()
            try:
                cur = con.cursor()
                # Delete tasks based on window_start year prefix
                year_prefix = f"{int(year):04d}-"
                cur.execute(
                    "DELETE FROM tasks WHERE window_start LIKE ?",
                    (year_prefix + "%",)
                )
                deleted = cur.rowcount if cur.rowcount is not None else 0
                con.commit()
                return deleted
            finally:
                con.close()

    def clear_tasks_for_staff_year_preserve(self, staff_id: str, year: int, preserve_task_ids: Optional[List[str]] = None) -> int:
        """Delete tasks for a staff/year but preserve any task_ids in preserve_task_ids.
        Returns number of rows deleted."""
        with self._lock:
            con = self._connect()
            try:
                cur = con.cursor()
                year_prefix = f"{int(year):04d}-"
                if preserve_task_ids:
                    placeholders = ",".join(["?" for _ in preserve_task_ids])
                    q = f"DELETE FROM tasks WHERE window_start LIKE ? AND task_id NOT IN ({placeholders})"
                    args = [year_prefix + "%"] + list(preserve_task_ids)
                    cur.execute(q, args)
                else:
                    cur.execute("DELETE FROM tasks WHERE window_start LIKE ?", (year_prefix + "%",))
                deleted = cur.rowcount if cur.rowcount is not None else 0
                con.commit()
                return deleted
            finally:
                con.close()
    
    def upsert_tasks(self, tasks: Iterable[TaskRow]) -> int:
        """Insert tasks; ignore if already present."""
        rows = list(tasks)
        if not rows:
            return 0
        with self._lock:
            con = self._connect()
            try:
                cur = con.cursor()
                cur.executemany(
                    """
                    INSERT OR IGNORE INTO tasks
                    (task_id, kpa_code, title, window_start, window_end, cadence, min_required, stretch_target, lead_lag, hints_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            t.task_id,
                            t.kpa_code,
                            t.title,
                            t.window_start,
                            t.window_end,
                            t.cadence,
                            int(t.min_required),
                            int(t.stretch_target),
                            t.lead_lag,
                            t.hints_json,
                        )
                        for t in rows
                    ],
                )
                con.commit()
                return cur.rowcount if cur.rowcount is not None else 0
            finally:
                con.close()

    def list_tasks_for_window(self, year: int, months: List[int], kpa_code: Optional[str] = None) -> List[sqlite3.Row]:
        """Return tasks whose window overlaps any month window (month-expanded tasks expected)."""
        # Since our tasks are expanded per-month, we simply filter by window_start prefix "YYYY-MM-01"
        prefixes = [f"{int(year):04d}-{m:02d}-" for m in months]
        with self._lock:
            con = self._connect()
            try:
                q = "SELECT * FROM tasks WHERE (" + " OR ".join(["window_start LIKE ?"] * len(prefixes)) + ")"
                args: List[Any] = [p + "%" for p in prefixes]
                if kpa_code:
                    q += " AND kpa_code = ?"
                    args.append(kpa_code)
                q += " ORDER BY kpa_code, window_start, title"
                return list(con.execute(q, args).fetchall())
            finally:
                con.close()

    # ----------------------------
    # Evidence management
    # ----------------------------
    def insert_evidence(
        self,
        *,
        evidence_id: str,
        sha1: str,
        staff_id: str,
        year: int,
        month_bucket: str,
        kpa_code: str,
        rating: str,
        tier: str,
        file_path: str,
        meta: Dict[str, Any],
    ) -> None:
        # Merge with any existing evidence metadata to avoid losing user-asserted fields
        new_meta = dict(meta or {})
        with self._lock:
            con = self._connect()
            try:
                # Fetch existing row if present
                cur = con.execute("SELECT meta_json, rating, tier FROM evidence WHERE evidence_id=?", (evidence_id,))
                existing = cur.fetchone()
                if existing:
                    try:
                        existing_meta = json.loads(existing["meta_json"] or "{}")
                    except Exception:
                        existing_meta = {}

                    # Preserve user-asserted explanatory fields unless new_meta explicitly provides them
                    for key in ("user_explanation", "target_task_id"):
                        if key in existing_meta and key not in new_meta:
                            new_meta[key] = existing_meta.get(key)

                    # Preserve previous rating/tier if new values are empty or generic
                    if (not rating or str(rating).strip().lower() in ("", "n/a", "none")) and existing.get("rating"):
                        rating = existing["rating"]
                    if (not tier or str(tier).strip().lower() in ("", "n/a", "none")) and existing.get("tier"):
                        tier = existing["tier"]

                    # Also merge other meta keys, preferring new_meta values
                    merged = dict(existing_meta)
                    merged.update(new_meta)
                    meta_json = json.dumps(merged or {}, ensure_ascii=False)
                else:
                    meta_json = json.dumps(new_meta or {}, ensure_ascii=False)

                con.execute(
                    """
                    INSERT OR REPLACE INTO evidence
                    (evidence_id, sha1, staff_id, year, month_bucket, kpa_code, rating, tier, file_path, meta_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (evidence_id, sha1, staff_id, int(year), month_bucket, kpa_code, str(rating), str(tier), file_path, meta_json),
                )
                con.commit()
            finally:
                con.close()

    def list_evidence(self, staff_id: str, year: int, *, month_bucket: Optional[str] = None, kpa_code: Optional[str] = None) -> List[sqlite3.Row]:
        with self._lock:
            con = self._connect()
            try:
                q = "SELECT * FROM evidence WHERE staff_id=? AND year=?"
                args: List[Any] = [staff_id, int(year)]
                if month_bucket:
                    q += " AND month_bucket=?"
                    args.append(month_bucket)
                if kpa_code:
                    q += " AND kpa_code=?"
                    args.append(kpa_code)
                q += " ORDER BY rowid DESC"
                return list(con.execute(q, args).fetchall())
            finally:
                con.close()

    def get_evidence(self, evidence_id: str) -> Optional[sqlite3.Row]:
        with self._lock:
            con = self._connect()
            try:
                r = con.execute("SELECT * FROM evidence WHERE evidence_id=?", (evidence_id,)).fetchone()
                return r
            finally:
                con.close()

    # ----------------------------
    # Mapping edges
    # ----------------------------
    def upsert_mapping(self, evidence_id: str, task_id: str, *, mapped_by: str, confidence: float) -> None:
        with self._lock:
            con = self._connect()
            try:
                # If this is an asserted mapping, persist it first so it survives cases
                # where the target task does not exist (foreign key would block evidence_task insert).
                try:
                    if isinstance(mapped_by, str) and "asserted" in mapped_by:
                        cur = con.execute("SELECT staff_id, year FROM evidence WHERE evidence_id=?", (evidence_id,))
                        ev = cur.fetchone()
                        staff = ev["staff_id"] if ev else None
                        yr = int(ev["year"]) if ev and ev["year"] is not None else None
                        con.execute(
                            """
                            INSERT OR REPLACE INTO asserted_mappings
                            (evidence_id, task_id, mapped_by, confidence, staff_id, year, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (evidence_id, task_id, mapped_by, float(confidence), staff, yr, _utc_now_iso()),
                        )
                except Exception:
                    pass

                # Then attempt to create the evidence_task edge; it may fail if the task doesn't exist.
                try:
                    con.execute(
                        """
                        INSERT OR REPLACE INTO evidence_task
                        (evidence_id, task_id, mapped_by, confidence, created_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (evidence_id, task_id, mapped_by, float(confidence), _utc_now_iso()),
                    )
                except Exception:
                    # Don't let task FK failures stop asserted mapping persistence.
                    pass
                con.commit()
            finally:
                con.close()

    def get_asserted_mappings_for_staff_year(self, staff_id: str, year: int) -> List[Tuple[str, str, str, float]]:
        """Return persisted asserted mappings for a staff/year as (evidence_id, task_id, mapped_by, confidence, task_title).
        The task_title may be empty; caller can attempt remapping by title or other heuristics."""
        with self._lock:
            con = self._connect()
            try:
                rows = con.execute(
                    "SELECT evidence_id, task_id, mapped_by, confidence FROM asserted_mappings WHERE staff_id=? AND year=?",
                    (staff_id, int(year)),
                ).fetchall()
                return [(r["evidence_id"], r["task_id"], r["mapped_by"], float(r["confidence"])) for r in rows]
            finally:
                con.close()

    def list_mappings_for_evidence(self, evidence_id: str) -> List[sqlite3.Row]:
        with self._lock:
            con = self._connect()
            try:
                return list(
                    con.execute(
                        """
                        SELECT et.*, t.kpa_code, t.title, t.window_start, t.window_end
                        FROM evidence_task et
                        JOIN tasks t ON t.task_id = et.task_id
                        WHERE et.evidence_id=?
                        ORDER BY et.confidence DESC, t.kpa_code, t.title
                        """,
                        (evidence_id,),
                    ).fetchall()
                )
            finally:
                con.close()

    def get_mappings_for_staff_year(self, staff_id: str, year: int) -> List[Tuple[str, str, str, float, str]]:
        """Return list of (evidence_id, task_id, mapped_by, confidence, task_title) for a staff/year."""
        with self._lock:
            con = self._connect()
            try:
                q = """
                    SELECT et.evidence_id, et.task_id, et.mapped_by, et.confidence, t.title
                    FROM evidence_task et
                    JOIN evidence e ON e.evidence_id = et.evidence_id
                    LEFT JOIN tasks t ON t.task_id = et.task_id
                    WHERE e.staff_id=? AND e.year=?
                """
                rows = con.execute(q, (staff_id, int(year))).fetchall()
                return [
                    (r["evidence_id"], r["task_id"], r["mapped_by"], float(r["confidence"]), r["title"] or "")
                    for r in rows
                ]
            finally:
                con.close()

    # ----------------------------
    # Progress computation (midyear/endyear)
    # ----------------------------
    def compute_window_progress(self, staff_id: str, year: int, months: List[int]) -> Dict[str, Any]:
        """Compute missing tasks + completion metrics for a window."""
        # Tasks expected in window
        task_rows = self.list_tasks_for_window(int(year), months)
        task_ids = [r["task_id"] for r in task_rows]

        with self._lock:
            con = self._connect()
            try:
                # Mapped tasks within window for staff/year evidence
                # Join evidence->evidence_task and filter by staff/year and month_bucket prefix
                prefixes = [f"{int(year):04d}-{m:02d}" for m in months]
                q = """
                    SELECT DISTINCT et.task_id
                    FROM evidence_task et
                    JOIN evidence e ON e.evidence_id = et.evidence_id
                    WHERE e.staff_id=? AND e.year=? AND (""" + " OR ".join(["e.month_bucket LIKE ?"] * len(prefixes)) + """)
                """
                args: List[Any] = [staff_id, int(year)] + [p + "%" for p in prefixes]
                mapped = set([row["task_id"] for row in con.execute(q, args).fetchall()])
            finally:
                con.close()

        missing = [dict(r) for r in task_rows if r["task_id"] not in mapped]

        # completion % by kpa
        by_kpa: Dict[str, Dict[str, Any]] = {}
        for r in task_rows:
            k = r["kpa_code"]
            by_kpa.setdefault(k, {"expected": 0, "completed": 0, "pct": 0.0})
            by_kpa[k]["expected"] += 1
            if r["task_id"] in mapped:
                by_kpa[k]["completed"] += 1
        for k, v in by_kpa.items():
            v["pct"] = 0.0 if v["expected"] == 0 else round(100.0 * v["completed"] / v["expected"], 1)

        return {
            "staff_id": staff_id,
            "year": int(year),
            "months": months,
            "expected_tasks": len(task_rows),
            "completed_tasks": len(mapped),
            "missing_tasks": missing,
            "by_kpa": by_kpa,
        }
