from __future__ import annotations

"""
offline_app_gui_llm_csv.py (FIXED)

What this version fixes / adds
------------------------------
1) Restores the older GUI layout you preferred:
   - Scrollable top section (header + staff + expectations + scan controls)
   - Bottom PanedWindow where BOTH the evidence table and the activity log remain visible
     and can be resized (drag the splitter).

2) Implements *true contextual scoring with Ollama* (not just an impact paragraph):
   - Uses frontend.offline_app.contextual_scorer.contextual_score
   - Feeds: evidence text + staff contract context + TA/PA expectations summary
   - Returns: primary KPA + rating (1–5) + tier + short impact summary

3) Keeps deterministic NWU brain scoring as a provenance layer:
   - The brain still produces values/policy hits (and can suggest KPA)
   - The GUI writes both the final contextual score and raw_llm_json into the evidence CSV

Drop-in location
----------------
Place this file in:
    frontend/offline_app/offline_app_gui_llm_csv.py

Requires (already in your repo):
    backend/staff_profile.py
    backend/contracts/task_agreement_import.py
    backend/contracts/pa_excel.py
    backend/expectation_engine.py
    backend/nwu_brain_scorer.py
    backend/vamp_master.py
    backend/evidence_store.py

"""

import csv
import datetime as _dt
import hashlib
import json
import os
import queue
import threading
import time
import traceback
try:
    import requests
except Exception:
    requests = None
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ---------------------------
# Path bootstrap (Windows-friendly)
# When you run:  python frontend/offline_app/offline_app_gui_llm_csv.py
# Python sets sys.path[0] to this script's folder, NOT the repo root.
# We therefore add the repo root (the folder that contains /backend) to sys.path.
# ---------------------------
import sys

def _ensure_repo_root_on_sys_path() -> Path:
    here = Path(__file__).resolve()
    for parent in [here] + list(here.parents):
        if (parent / 'backend').is_dir():
            if str(parent) not in sys.path:
                sys.path.insert(0, str(parent))
            return parent
    # Fallback: current working directory
    cwd = Path.cwd().resolve()
    if (cwd / 'backend').is_dir() and str(cwd) not in sys.path:
        sys.path.insert(0, str(cwd))
        return cwd
    return cwd

REPO_ROOT = _ensure_repo_root_on_sys_path()


try:
    from PIL import Image, ImageTk  # type: ignore
except Exception:
    Image = None
    ImageTk = None

# ---------------------------
# Backend imports (expected)
# ---------------------------
try:
    from backend.staff_profile import (
        StaffProfile,
        create_or_load_profile,
        staff_is_director_level,
    )  # type: ignore
except Exception as e:
    raise RuntimeError("Missing backend.staff_profile. Please ensure you're running from the repo root.") from e

try:
    from backend.contracts.task_agreement_import import import_task_agreement_excel  # type: ignore
except Exception:
    import_task_agreement_excel = None

try:
    from backend.contracts.pa_excel import (  # type: ignore
        generate_initial_pa,
        generate_mid_year_review,
        generate_final_review,
    )
except Exception:
    generate_initial_pa = None
    generate_mid_year_review = None
    generate_final_review = None

try:
    from backend.contracts.pa_generator import generate_pa_skeleton_from_ta  # type: ignore
except Exception:
    generate_pa_skeleton_from_ta = None

try:
    from backend.contracts.pa_enricher_ai import enrich_pa_with_ai  # type: ignore
except Exception:
    enrich_pa_with_ai = None

try:
    from backend.contracts.validation import validate_ta_contract  # type: ignore
except Exception:
    validate_ta_contract = None

try:
    from backend.expectation_engine import build_staff_expectations, load_staff_expectations  # type: ignore
except Exception:
    build_staff_expectations = None
    load_staff_expectations = None

try:
    from backend.nwu_formats import parse_nwu_ta  # type: ignore
except Exception:
    parse_nwu_ta = None

try:
    from backend.expectation_engine import parse_task_agreement  # type: ignore
except Exception:
    parse_task_agreement = None

try:
    from backend.vamp_master import (
        ExtractionResult,
        extract_text_for,
        generate_run_id,
        ingest_paths,
    )  # type: ignore
except Exception:
    ingest_paths = None
    extract_text_for = None
    generate_run_id = lambda: f"run-fallback-{hashlib.sha1(os.urandom(8)).hexdigest()[:8]}"  # type: ignore

try:
    from backend.nwu_brain_scorer import brain_score_evidence  # type: ignore
except Exception:
    brain_score_evidence = None

try:
    from backend.evidence_store import append_evidence_row  # type: ignore
except Exception:
    append_evidence_row = None

# Contextual scorer (Ollama JSON scoring)
try:
    from frontend.offline_app.contextual_scorer import contextual_score  # type: ignore
except Exception:
    contextual_score = None


# ---------------------------
# Paths / constants
# ---------------------------
HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[2]

ASSETS_DIR = PROJECT_ROOT / "frontend" / "assets"
OFFLINE_RESULTS_DIR = PROJECT_ROOT / "output" / "offline_results"
OFFLINE_RESULTS_DIR.mkdir(parents=True, exist_ok=True)

DATA_DIR = PROJECT_ROOT / "backend" / "data"

APP_TITLE = "VAMP – Offline Evidence Scanner"
APP_SUBTITLE = "Expectation-aware monthly scoring (NWU brain + Ollama contextual score)"

MONTH_OPTIONS: List[Tuple[str, str]] = [
    ("1", "January"), ("2", "February"), ("3", "March"), ("4", "April"),
    ("5", "May"), ("6", "June"), ("7", "July"), ("8", "August"),
    ("9", "September"), ("10", "October"), ("11", "November"), ("12", "December"),
]

KPA_OPTIONS: List[Tuple[str, str]] = [
    ("AUTO", "Auto"),
    ("KPA1", "Teaching and Learning"),
    ("KPA2", "Occupational Health & Safety"),
    ("KPA3", "Research and Innovation"),
    ("KPA4", "Academic leadership and management"),
    ("KPA5", "Social Responsiveness"),
]

TABLE_COLUMNS = [
    "time",
    "filename",
    "kpa",
    "rating",
    "tier",
    "brain_notes",
    "ai_impact",
]

CSV_COLUMNS = [
    "run_id",
    "filename",
    "file_path",
    "file",
    "month",
    "kpa_code",
    "kpa_name",
    "kpa_codes",
    "kpi_labels",
    "rating",
    "rating_label",
    "tier_label",
    "status",
    "confidence",
    "impact_summary",
    "status_reason",
    "extract_status",
    "extract_error",
    "evidence_type",
]


def _now_ts() -> str:
    return _dt.datetime.now().strftime("%H:%M:%S")


def _play_sound(filename: str) -> None:
    """
    Optional UX sugar. Looks for the file in assets, then in the current folder.
    """
    try:
        import winsound  # type: ignore
    except Exception:
        return

    candidates = [
        ASSETS_DIR / filename,
        HERE / filename,
        PROJECT_ROOT / filename,
    ]
    for p in candidates:
        if p.exists():
            try:
                winsound.PlaySound(str(p), winsound.SND_FILENAME | winsound.SND_ASYNC)
            except Exception:
                pass
            return


def _open_file(path: Path) -> None:
    try:
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore
        else:
            import subprocess
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        pass


def _guess_evidence_type(path: Path) -> str:
    s = path.suffix.lower()
    if s == ".pdf":
        return "pdf"
    if s in {".doc", ".docx"}:
        return "word"
    if s in {".ppt", ".pptx"}:
        return "powerpoint"
    if s in {".xlsx", ".xls", ".xlsm"}:
        return "excel"
    if s in {".msg", ".eml"}:
        return "email"
    return s.lstrip(".") or "other"


def _default_ctx(kpa_hint: str) -> Dict[str, Any]:
    ctx: Dict[str, Any] = {
        "primary_kpa_code": kpa_hint or "",
        "primary_kpa_name": "",
        "tier_label": "Developmental",
        "rating": None,
        "rating_label": "Unrated",
        "impact_summary": "",
        "raw_llm_json": {},
        "values_hits": [],
    }
    return ctx


def _normalize_ctx(ctx: Optional[Dict[str, Any]], kpa_hint: str) -> Dict[str, Any]:
    base = _default_ctx(kpa_hint)
    merged = base.copy()
    if ctx:
        merged.update(ctx)
    merged.setdefault("primary_kpa_code", kpa_hint or "")
    merged.setdefault("primary_kpa_name", "")
    merged.setdefault("tier_label", "Developmental")
    merged.setdefault("rating", None)
    merged.setdefault("rating_label", "Unrated")
    merged.setdefault("impact_summary", "")
    merged.setdefault("raw_llm_json", {})
    merged.setdefault("values_hits", [])
    return merged


def process_artefact(
    *,
    path: Path,
    month_bucket: str,
    run_id: str,
    profile: Any,
    contract_context: str,
    kpa_hint: str,
    use_ollama: bool,
    prefer_llm_rating: bool,
    log: Optional[Any] = None,
    extract_fn=extract_text_for,
    contextual_fn=contextual_score,
    brain_fn=brain_score_evidence,
) -> Tuple[Dict[str, Any], Dict[str, Any], str]:
    """Process a single artefact into a CSV/UI row.

    Extraction/scoring functions are injectable for testing.
    """

    logger = log or (lambda *args, **kwargs: None)
    extract_status = "ok"
    extract_error = ""
    extracted_text = ""
    review_reason = ""

    if extract_fn is None:
        extract_status = "failed"
        extract_error = "text extractor unavailable"
        review_reason = "Batch1 extraction unavailable"
        logger(f"{path.name} → ❌ Failed to extract text: {extract_error}")
    else:
        try:
            extraction = extract_fn(path)
            if isinstance(extraction, ExtractionResult):
                extracted_text = extraction.extracted_text or ""
                extract_status = extraction.extract_status or "failed"
                extract_error = extraction.extract_error or ""
            elif isinstance(extraction, dict):
                extracted_text = extraction.get("extracted_text", "") or ""
                extract_status = extraction.get("extract_status", "failed") or "failed"
                extract_error = extraction.get("extract_error") or ""
            else:
                extracted_text = extraction or ""
                extract_status = "ok" if str(extracted_text).strip() else "failed"

            if not extracted_text.strip() and extract_status == "ok":
                extract_status = "failed"
                extract_error = extract_error or "no text extracted"
        except Exception as e:
            extract_status = "failed"
            extract_error = str(e)
            review_reason = f"Batch1 extraction error: {e}"
            logger(f"{path.name} → ❌ Failed to extract text: {e}")

    if extract_status != "ok" and not review_reason:
        origin = "Batch1 extraction"
        if extract_status == "image_no_ocr":
            origin = "Batch1 image OCR"
        review_reason = f"{origin}: {extract_error or 'no text extracted'}"

    ctx: Dict[str, Any] = _default_ctx(kpa_hint)
    scoring_available = False
    scoring_error = False

    if extract_status == "ok":
        if use_ollama and contextual_fn is not None:
            scoring_available = True
            try:
                ctx = contextual_fn(
                    evidence_text=extracted_text,
                    contract_context=contract_context,
                    kpa_hint_code=kpa_hint,
                    staff_id=getattr(profile, "staff_id", ""),
                    source_path=path,
                    prefer_llm_rating=prefer_llm_rating,
                )
            except Exception as ex:
                scoring_error = True
                review_reason = review_reason or f"Batch7 contextual scoring error: {ex}"
                logger(f"{path.name} → ⚠️ Contextual scoring error (fallback to brain): {ex}")
                ctx = {}
        if (not ctx or not ctx.get("primary_kpa_code")) and brain_fn is not None:
            scoring_available = True
            try:
                ctx = brain_fn(path=path, full_text=extracted_text, kpa_hint_code=kpa_hint) or ctx
                ctx.setdefault("impact_summary", "")
                ctx.setdefault("raw_llm_json", {})
            except Exception as ex:
                scoring_error = True
                review_reason = review_reason or f"Batch7 brain scoring error: {ex}"
                logger(f"{path.name} → ❌ Brain scoring error: {ex}")
        ctx = _normalize_ctx(ctx, kpa_hint)
    else:
        ctx = _normalize_ctx(ctx, kpa_hint)

    if extract_status != "ok" or scoring_error:
        status = "NEEDS_REVIEW"
    elif scoring_available:
        status = "SCORED"
    else:
        status = "UNSCORABLE"

    if status != "SCORED" and not review_reason:
        if extract_status != "ok":
            review_reason = f"Batch1 extraction issue: {extract_error or 'no text'}"
        elif not scoring_available:
            review_reason = "Batch7 scoring unavailable"
        elif scoring_error:
            review_reason = "Batch7 scoring error"

    evidence_type = _guess_evidence_type(path)
    kpa_code = str(ctx.get("primary_kpa_code") or "").strip()
    kpa_name = str(ctx.get("primary_kpa_name") or "").strip() or "Unknown"
    impact = (ctx.get("impact_summary") or ctx.get("contextual_response") or "").strip()
    if not impact and review_reason:
        impact = review_reason
    confidence = ctx.get("confidence")
    try:
        confidence_val = float(confidence) if confidence is not None else None
    except Exception:
        confidence_val = None
    confidence_pct = "" if confidence_val is None else round(confidence_val * 100)

    row = {
        "run_id": run_id,
        "filename": path.name,
        "file_path": str(path),
        "file": path.name,
        "month": month_bucket,
        "kpa_code": kpa_code,
        "kpa_name": kpa_name,
        "kpa_codes": kpa_code,
        "kpi_labels": "",
        "rating": "" if ctx.get("rating") is None else ctx.get("rating"),
        "rating_label": str(ctx.get("rating_label") or "").strip() or "Unrated",
        "tier_label": str(ctx.get("tier_label") or "").strip() or "Developmental",
        "status": status,
        "confidence": confidence_pct,
        "impact_summary": impact,
        "status_reason": review_reason,
        "evidence_type": evidence_type,
        "extract_status": extract_status,
        "extract_error": extract_error,
    }
    kpi_matches = ctx.get("kpi_matches")
    if isinstance(kpi_matches, list):
        row["kpi_labels"] = "; ".join(str(k) for k in kpi_matches if str(k).strip())
    return row, ctx, impact


def _sha1(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


class OfflineApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()

        self.title(APP_TITLE)
        self.geometry("1180x820")
        self.minsize(980, 700)

        # State
        self.profile: Optional[StaffProfile] = None
        self.staff_profile: Optional[StaffProfile] = None
        self.task_agreement_path: Optional[Path] = None
        self.pa_skeleton_path: Optional[Path] = None
        self.pa_initial_path: Optional[Path] = None
        self.pa_mid_path: Optional[Path] = None
        self.pa_final_path: Optional[Path] = None
        self.current_evidence_folder: Optional[Path] = None
        self.evidence_folder: Optional[Path] = None

        # --- UI/worker state flags (MUST exist before any _refresh_button_states calls) ---
        self.ta_import_running = False
        self.pa_generate_running = False
        self.ai_enrich_running = False
        self.scan_running = False
        self.stop_requested = False

        self.ta_valid = False
        self.ta_validation_errors: List[str] = []
        self.pa_skeleton_ready = False
        self.pa_ai_ready = False
        self.ai_enrich_status = "Not started"

        self.contract: Optional[Dict[str, Any]] = None
        self.pa_ai_path: Optional[Path] = None

        self.expectations: Dict[str, Any] = {}
        self.rows: List[Dict[str, Any]] = []
        self.detail_rows: Dict[str, Dict[str, Any]] = {}
        self._detail_counter = 0
        self.contract_validation_errors: List[str] = []
        self.contract_validation_warnings: List[str] = []
        self.kpa2_modules: List[str] = []
        self.session_state: Dict[str, Any] = {}
        self.pa_skeleton_rows: List[List[Any]] = []

        self.filter_status_var = tk.StringVar(value="All")
        self.filter_kpa_var = tk.StringVar(value="All")
        self.filter_type_var = tk.StringVar(value="All")

        self.selected_detail: Dict[str, Any] = {}

        # Status badge vars (top-of-UI indicators)
        self.contract_loaded_status_var = tk.StringVar(value="Contract Loaded: ❌")
        self.ta_imported_status_var = tk.StringVar(value="TA Imported: ❌")
        self.pa_skeleton_status_var = tk.StringVar(value="PA Skeleton: ❌")
        self.ai_enriched_status_var = tk.StringVar(value="AI Enriched: ❌")

        # UI handoff queue to keep worker threads away from Tk operations
        self.ui_queue: "queue.Queue[Tuple[Any, ...]]" = queue.Queue()
        self.after(80, self._drain_ui_queue)

        self._scan_thread: Optional[threading.Thread] = None
        self._stop_flag = threading.Event()
        self.current_run_id: str = generate_run_id()

        # Styling
        self._colors = {
            "bg": "#0b0b10",
            "panel": "#12121b",
            "fg": "#f2f2f5",
            "muted": "#b8b8c7",
            "accent": "#c1121f",   # blood red
            "accent2": "#ff4d6d",  # glow red/pink
            "line": "#2b2b3a",
            "green": "#2dd4bf",
            "warn": "#f59e0b",
        }

        self.cinzel_family = "Cinzel"
        self._configure_styles()

        # Layout: three vertical zones
        self.configure(bg=self._colors["bg"])
        self.top_panel = tk.Frame(self, bg=self._colors["bg"], height=260)
        self.top_panel.grid(row=0, column=0, sticky="nsew")
        self.middle_panel = tk.Frame(self, bg=self._colors["bg"])
        self.middle_panel.grid(row=1, column=0, sticky="nsew")
        self.bottom_panel = tk.Frame(self, bg=self._colors["bg"])
        self.bottom_panel.grid(row=2, column=0, sticky="nsew")

        self.rowconfigure(0, weight=0, minsize=240)
        self.rowconfigure(1, weight=3)
        self.rowconfigure(2, weight=2, minsize=220)
        self.columnconfigure(0, weight=1)

        self._build_top_dashboard()
        self._build_middle_table()
        self._build_bottom_split()

        self.bind("<Escape>", lambda e: self._stop_scan())
        self._refresh_button_states()

    # ---------------------------
    # Styles
    # ---------------------------
    def _configure_styles(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure(".", background=self._colors["bg"], foreground=self._colors["fg"])
        style.configure("Title.TLabel", font=(self.cinzel_family, 20, "bold"), foreground=self._colors["accent2"], background=self._colors["bg"])
        style.configure("Subtitle.TLabel", font=(self.cinzel_family, 11), foreground=self._colors["muted"], background=self._colors["bg"])
        style.configure("Section.TLabel", font=(self.cinzel_family, 12, "bold"), foreground=self._colors["accent2"], background=self._colors["panel"])

        style.configure("TButton", font=(self.cinzel_family, 10, "bold"), padding=7, background=self._colors["accent"], foreground="white", borderwidth=0)
        style.map(
            "TButton",
            background=[("active", self._colors["accent2"]), ("pressed", self._colors["accent2"])],
        )

        style.configure("TCombobox", fieldbackground="#0f0f17", background=self._colors["panel"], foreground=self._colors["fg"])
        style.configure("Treeview", background="#0f0f17", fieldbackground="#0f0f17", foreground=self._colors["fg"], bordercolor=self._colors["line"])
        style.configure("Treeview.Heading", background=self._colors["panel"], foreground=self._colors["accent2"], font=(self.cinzel_family, 10, "bold"))

    def _update_stage_label(self) -> None:
        if not getattr(self, "staff_profile", None):
            txt = "Stage: Load profile"
        elif not self.ta_valid:
            txt = "Stage: Import TA"
        elif self.ta_valid and not self.pa_skeleton_ready:
            txt = "Stage: Generate Skeleton"
        elif self.pa_skeleton_ready and not self.pa_ai_ready:
            txt = "Stage: Generate AI PA (optional)"
        else:
            txt = "Stage: Export"
        if hasattr(self, "lbl_stage"):
            self.lbl_stage.configure(text=txt)

    def _update_status_indicators(self) -> None:
        contract_loaded = bool(getattr(self, "staff_profile", None))
        ta_imported = bool(getattr(self, "ta_valid", False))
        skeleton_ready = bool(getattr(self, "pa_skeleton_ready", False))
        ai_ready = bool(getattr(self, "pa_ai_ready", False))
        ai_running = bool(getattr(self, "ai_enrich_running", False))

        self.contract_loaded_status_var.set(
            f"Contract Loaded: {'✅' if contract_loaded else '❌'}"
        )
        self.ta_imported_status_var.set(
            f"TA Imported: {'✅' if ta_imported else '❌'}"
        )
        self.pa_skeleton_status_var.set(
            f"PA Skeleton: {'✅' if skeleton_ready else '❌'}"
        )

        ai_icon = "❌"
        ai_suffix = self.ai_enrich_status or "Not started"
        if ai_ready:
            ai_icon = "✅"
            ai_suffix = "Ready"
        elif ai_running:
            ai_icon = "⚠️"
            ai_suffix = "In progress"
        elif ai_suffix.lower().startswith("timeout"):
            ai_icon = "⚠️"

        self.ai_enriched_status_var.set(f"AI Enriched: {ai_icon} {ai_suffix}")

    def _refresh_button_states(self) -> None:
        has_profile = bool(getattr(self, "staff_profile", None))
        ta_valid = bool(getattr(self, "ta_valid", False))
        skeleton_ready = bool(getattr(self, "pa_skeleton_ready", False))
        ai_ready = bool(getattr(self, "pa_ai_ready", False))
        ai_running = bool(getattr(self, "ai_enrich_running", False))
        contract_invalid = bool(getattr(self, "contract_validation_errors", []))
        if hasattr(self, "btn_import_ta"):
            self.btn_import_ta.configure(state=("normal" if has_profile else "disabled"))

        if hasattr(self, "btn_gen_skeleton"):
            self.btn_gen_skeleton.configure(state=("normal" if getattr(self, "ta_valid", False) else "disabled"))
        if hasattr(self, "btn_gen_ai"):
            self.btn_gen_ai.configure(state=("normal" if getattr(self, "pa_skeleton_ready", False) else "disabled"))

        if hasattr(self, "btn_export_pa"):
            self.btn_export_pa.configure(state=("normal" if getattr(self, "pa_skeleton_ready", False) else "disabled"))

        if hasattr(self, "start_btn"):
            evidence_folder = getattr(self, "evidence_folder", None) or self.current_evidence_folder
            self.start_btn.configure(state=("normal" if evidence_folder else "disabled"))
        if hasattr(self, "btn_stop_scan"):
            self.btn_stop_scan.configure(state=("normal" if getattr(self, "scan_running", False) else "disabled"))

        if hasattr(self, "btn_start_scan"):
            evidence_folder = getattr(self, "evidence_folder", None) or self.current_evidence_folder
            self.btn_start_scan.configure(state=("normal" if evidence_folder else "disabled"))
        if hasattr(self, "btn_stop_scan"):
            self.btn_stop_scan.configure(state=("normal" if getattr(self, "scan_running", False) else "disabled"))

        self._update_stage_label()
        self._update_status_indicators()

    # ---------------------------
    # UI builders
    # ---------------------------
    def _build_top_dashboard(self) -> None:
        bg = self._colors["bg"]
        wrapper = self._panel(self.top_panel)
        wrapper.pack(fill="both", expand=True, padx=12, pady=10)
        wrapper.columnconfigure(0, weight=1)
        wrapper.columnconfigure(1, weight=1)
        wrapper.columnconfigure(2, weight=1)
        wrapper.rowconfigure(2, weight=1)

        # Header row
        header = tk.Frame(wrapper, bg=bg)
        header.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(4, 8))
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text=APP_TITLE, style="Title.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(header, text=APP_SUBTITLE, style="Subtitle.TLabel").grid(row=1, column=0, columnspan=3, sticky="w")

        status_row = tk.Frame(wrapper, bg=self._colors["panel"])
        status_row.grid(row=1, column=0, columnspan=3, sticky="ew", padx=4, pady=(0, 6))
        for idx in range(4):
            status_row.columnconfigure(idx, weight=1)

        def _status_label(var: tk.StringVar, col: int) -> None:
            tk.Label(
                status_row,
                textvariable=var,
                bg=self._colors["panel"],
                fg=self._colors["fg"],
                font=(self.cinzel_family, 10, "bold"),
                anchor="w",
            ).grid(row=0, column=col, sticky="ew", padx=8, pady=4)

        _status_label(self.contract_loaded_status_var, 0)
        _status_label(self.ta_imported_status_var, 1)
        _status_label(self.pa_skeleton_status_var, 2)
        _status_label(self.ai_enriched_status_var, 3)

        # Column 1: staff profile summary and contract status
        col1 = self._panel(wrapper)
        col1.grid(row=2, column=0, sticky="nsew", padx=(8, 6), pady=6)
        col1.columnconfigure(1, weight=1)
        col1.columnconfigure(2, weight=1)
        ttk.Label(col1, text="Staff Profile", style="Section.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", padx=10, pady=(8, 4))

        self.lbl_stage = tk.Label(
            col1,
            text="Stage: Load profile",
            bg=self._colors["panel"],
            fg=self._colors["fg"],
            font=(self.cinzel_family, 10, "bold"),
        )
        self.lbl_stage.grid(row=0, column=2, sticky="e", padx=10, pady=(8, 4))

        self.staff_id_var = tk.StringVar()
        self.staff_name_var = tk.StringVar()
        self.staff_pos_var = tk.StringVar()
        self.staff_faculty_var = tk.StringVar()
        self.staff_manager_var = tk.StringVar()
        self.staff_year_var = tk.StringVar(value=str(_dt.datetime.now().year))

        self.contract_status_var = tk.StringVar(value="❌ No Contract")
        self.contract_status_reason = "No valid Task/Performance Agreement loaded."

        profile_fields = [
            ("Staff Number", self.staff_id_var),
            ("Full Name", self.staff_name_var),
            ("Faculty", self.staff_faculty_var),
            ("Post Level", self.staff_pos_var),
            ("Performance Year", self.staff_year_var),
        ]
        for idx, (label, var) in enumerate(profile_fields, start=1):
            tk.Label(col1, text=f"{label}:", bg=self._colors["panel"], fg=self._colors["fg"], font=(self.cinzel_family, 10)).grid(
                row=idx, column=0, sticky="w", padx=10, pady=2
            )
            entry = tk.Entry(
                col1,
                textvariable=var,
                bg="#0f0f17",
                fg=self._colors["fg"],
                insertbackground=self._colors["fg"],
                highlightthickness=1,
                highlightbackground=self._colors["accent"],
            )
            entry.grid(row=idx, column=1, sticky="ew", padx=6, pady=2)

        self.lbl_contract_status = tk.Label(
            col1,
            text="Contract: INVALID_TA",
            bg=self._colors["panel"],
            fg=self._colors["warn"],
            font=(self.cinzel_family, 10, "bold"),
        )
        self.lbl_contract_status.grid(row=len(profile_fields) + 1, column=0, columnspan=3, sticky="w", padx=10, pady=(4, 2))

        self.lbl_flags = tk.Label(
            col1,
            text="Flags: none",
            bg=self._colors["panel"],
            fg=self._colors["muted"],
            font=(self.cinzel_family, 10),
        )
        self.lbl_flags.grid(row=len(profile_fields) + 2, column=0, columnspan=3, sticky="w", padx=10, pady=(0, 6))

        action_row = tk.Frame(col1, bg=self._colors["panel"])
        action_row.grid(row=len(profile_fields) + 3, column=0, columnspan=3, sticky="ew", padx=8, pady=(4, 10))
        ttk.Button(action_row, text="Enroll / Load", command=self._enroll).grid(row=0, column=0, padx=(0, 6))
        self.btn_import_ta = ttk.Button(action_row, text="Import Task Agreement", command=self._import_ta)
        self.btn_import_ta.grid(row=0, column=1, padx=(0, 6))
        self.btn_gen_skeleton = ttk.Button(action_row, text="Generate PA Skeleton", command=self._generate_pa_skeleton)
        self.btn_gen_skeleton.grid(row=0, column=2, padx=(0, 6))
        self.btn_gen_ai = ttk.Button(action_row, text="Generate PA (AI)", command=self._generate_pa_ai)
        self.btn_gen_ai.grid(row=0, column=3, padx=(0, 6))
        self.btn_export_pa = ttk.Button(action_row, text="Export PA Excel", command=self._export_pa_excel)
        self.btn_export_pa.grid(row=0, column=4, padx=(0, 6))

        self.staff_status = tk.Label(
            col1,
            text="Not enrolled",
            bg=self._colors["panel"],
            fg=self._colors["muted"],
            font=(self.cinzel_family, 10, "italic"),
        )
        self.staff_status.grid(row=len(profile_fields) + 4, column=0, columnspan=3, sticky="w", padx=10, pady=(2, 6))

        # Column 2: KPA breakdown table
        col2 = self._panel(wrapper)
        col2.grid(row=2, column=1, sticky="nsew", padx=6, pady=6)
        col2.columnconfigure(0, weight=1)
        ttk.Label(col2, text="KPA Hours & Weight Breakdown", style="Section.TLabel").grid(row=0, column=0, sticky="w", padx=10, pady=(8, 4))
        self.kpa_health_tree = ttk.Treeview(col2, columns=["kpa", "name", "hours", "weight", "status"], show="headings", height=6)
        headings = [
            ("kpa", "KPA"),
            ("name", "Name"),
            ("hours", "Hours"),
            ("weight", "Weight %"),
            ("status", "Status"),
        ]
        for cid, label in headings:
            self.kpa_health_tree.heading(cid, text=label)
            self.kpa_health_tree.column(cid, anchor="w", width=120)
        self.kpa_health_tree.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 8))
        ykpa = ttk.Scrollbar(col2, orient="vertical", command=self.kpa_health_tree.yview)
        self.kpa_health_tree.configure(yscrollcommand=ykpa.set)
        ykpa.grid(row=1, column=1, sticky="ns", pady=(0, 8))

        self.modules_var = tk.StringVar(value="Teaching modules: –")
        tk.Label(
            col2,
            textvariable=self.modules_var,
            bg=self._colors["panel"],
            fg=self._colors["fg"],
            font=(self.cinzel_family, 10),
            wraplength=320,
            justify="left",
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 6))

        # Column 3: Scan & export controls
        col3 = self._panel(wrapper)
        col3.grid(row=2, column=2, sticky="nsew", padx=(6, 8), pady=6)
        col3.columnconfigure(1, weight=1)
        ttk.Label(col3, text="Scan & Export", style="Section.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", padx=10, pady=(8, 4))

        self.folder_var = tk.StringVar(value="(no folder selected)")
        self.month_var = tk.StringVar(value=str(_dt.datetime.now().month))
        self.kpa_var = tk.StringVar(value="AUTO")
        self.use_ollama_score_var = tk.BooleanVar(value=True)
        self.prefer_llm_rating_var = tk.BooleanVar(value=True)

        tk.Label(col3, text="Evidence Folder", bg=self._colors["panel"], fg=self._colors["fg"], font=(self.cinzel_family, 10)).grid(row=1, column=0, sticky="w", padx=10, pady=4)
        tk.Entry(
            col3,
            textvariable=self.folder_var,
            bg="#0f0f17",
            fg=self._colors["fg"],
            insertbackground=self._colors["fg"],
            highlightthickness=1,
            highlightbackground=self._colors["accent"],
        ).grid(row=1, column=1, sticky="ew", padx=6, pady=4)
        ttk.Button(col3, text="Select", command=self._choose_folder).grid(row=1, column=2, padx=6, pady=4)

        tk.Label(col3, text="Performance Period", bg=self._colors["panel"], fg=self._colors["fg"], font=(self.cinzel_family, 10)).grid(row=2, column=0, sticky="w", padx=10, pady=4)
        ttk.Combobox(col3, textvariable=self.month_var, state="readonly", values=[m[0] for m in MONTH_OPTIONS], width=10).grid(row=2, column=1, sticky="w", padx=6, pady=4)

        tk.Label(col3, text="KPA Hint", bg=self._colors["panel"], fg=self._colors["fg"], font=(self.cinzel_family, 10)).grid(row=3, column=0, sticky="w", padx=10, pady=4)
        ttk.Combobox(col3, textvariable=self.kpa_var, state="readonly", values=[k[0] for k in KPA_OPTIONS], width=10).grid(row=3, column=1, sticky="w", padx=6, pady=4)

        tk.Checkbutton(
            col3,
            text="Use Ollama contextual scoring",
            variable=self.use_ollama_score_var,
            bg=self._colors["panel"],
            fg=self._colors["fg"],
            selectcolor=self._colors["panel"],
            activebackground=self._colors["panel"],
        ).grid(row=4, column=0, columnspan=3, sticky="w", padx=10, pady=(6, 2))
        tk.Checkbutton(
            col3,
            text="Prefer LLM rating over brain rating",
            variable=self.prefer_llm_rating_var,
            bg=self._colors["panel"],
            fg=self._colors["fg"],
            selectcolor=self._colors["panel"],
            activebackground=self._colors["panel"],
        ).grid(row=5, column=0, columnspan=3, sticky="w", padx=10, pady=(0, 6))

        btn_row = tk.Frame(col3, bg=self._colors["panel"])
        btn_row.grid(row=6, column=0, columnspan=3, sticky="ew", padx=8, pady=(4, 4))
        self.start_btn = ttk.Button(btn_row, text="Start Scan", command=self._start_scan)
        self.start_btn.grid(row=0, column=0, padx=(0, 6))
        self.btn_start_scan = self.start_btn
        self.btn_stop_scan = ttk.Button(btn_row, text="Stop Scan", command=self._stop_scan)
        self.btn_stop_scan.grid(row=0, column=1, padx=(0, 6))
        ttk.Button(btn_row, text="Export CSV", command=self._export_csv).grid(row=0, column=2, padx=(0, 6))
        self.export_pa_btn = ttk.Button(btn_row, text="Export PA Excel", command=self._generate_final)
        self.export_pa_btn.grid(row=0, column=3, padx=(0, 6))

        self.scan_status = tk.Label(col3, text="Idle", bg=self._colors["panel"], fg=self._colors["muted"], font=(self.cinzel_family, 10, "italic"))
        self.scan_status.grid(row=7, column=0, columnspan=3, sticky="w", padx=10, pady=(4, 4))

        self._refresh_kpa_breakdown()

    def _panel(self, parent) -> tk.Frame:
        f = tk.Frame(parent, bg=self._colors["panel"], highlightthickness=1, highlightbackground=self._colors["line"])
        return f

    def _build_middle_table(self) -> None:
        panel = self._panel(self.middle_panel)
        panel.pack(fill="both", expand=True, padx=12, pady=8)
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(2, weight=1)

        ttk.Label(panel, text="Evidence Decisions", style="Section.TLabel").grid(row=0, column=0, sticky="w", padx=10, pady=(6, 2))

        # Filters
        filters = tk.Frame(panel, bg=self._colors["panel"])
        filters.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 6))
        tk.Label(filters, text="Status", bg=self._colors["panel"], fg=self._colors["fg"], font=(self.cinzel_family, 10)).grid(row=0, column=0, padx=(0, 6))
        ttk.Combobox(filters, textvariable=self.filter_status_var, values=["All", "SCORED", "NEEDS_REVIEW", "UNSCORABLE"], state="readonly", width=14, postcommand=self._apply_filters).grid(row=0, column=1)
        tk.Label(filters, text="KPA", bg=self._colors["panel"], fg=self._colors["fg"], font=(self.cinzel_family, 10)).grid(row=0, column=2, padx=(12, 6))
        ttk.Combobox(filters, textvariable=self.filter_kpa_var, values=["All", "KPA1", "KPA2", "KPA3", "KPA4", "KPA5"], state="readonly", width=10, postcommand=self._apply_filters).grid(row=0, column=3)
        tk.Label(filters, text="Evidence Type", bg=self._colors["panel"], fg=self._colors["fg"], font=(self.cinzel_family, 10)).grid(row=0, column=4, padx=(12, 6))
        ttk.Combobox(filters, textvariable=self.filter_type_var, values=["All", "pdf", "word", "excel", "powerpoint", "email", "other"], state="readonly", width=12, postcommand=self._apply_filters).grid(row=0, column=5)

        self.tree = ttk.Treeview(panel, columns=TABLE_COLUMNS, show="headings")
        for c in TABLE_COLUMNS:
            label = c.replace("_", " ").title()
            self.tree.heading(c, text=label, command=lambda col=c: self._sort_tree(col, False))
            width = 120
            if c == "filename":
                width = 220
            elif c in {"brain_notes", "ai_impact"}:
                width = 200
            self.tree.column(c, width=width, anchor="w")
        self.tree.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 8))
        yscroll = ttk.Scrollbar(panel, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        yscroll.grid(row=2, column=1, sticky="ns", pady=(0, 8))
        self.tree.bind("<<TreeviewSelect>>", self._on_row_select)

        self.tree.tag_configure("NEEDS_REVIEW", background="#3b2f00", foreground=self._colors["fg"])
        self.tree.tag_configure("UNSCORABLE", background="#1f1f1f", foreground=self._colors["muted"], font=(self.cinzel_family, 10, "italic"))
        self.tree.tag_configure("SCORED", background="#101018", foreground=self._colors["fg"])

    def _build_bottom_split(self) -> None:
        pw = ttk.PanedWindow(self.bottom_panel, orient="horizontal")
        pw.pack(fill="both", expand=True, padx=12, pady=(4, 12))

        # Detail pane
        detail_frame = self._panel(pw)
        detail_frame.columnconfigure(0, weight=1)
        ttk.Label(detail_frame, text="Artefact Detail", style="Section.TLabel").grid(row=0, column=0, sticky="w", padx=10, pady=(8, 4))

        meta = tk.Frame(detail_frame, bg=self._colors["panel"])
        meta.grid(row=1, column=0, sticky="ew", padx=10)
        meta.columnconfigure(1, weight=1)
        self.detail_labels: Dict[str, tk.StringVar] = {}
        for idx, key in enumerate([
            "Filename",
            "Evidence Type",
            "Status",
            "Review Reason",
            "Final Rating",
            "Final Tier",
            "Confidence",
            "KPA",
            "KPI",
        ]):
            tk.Label(meta, text=f"{key}:", bg=self._colors["panel"], fg=self._colors["fg"], font=(self.cinzel_family, 10)).grid(row=idx, column=0, sticky="w", pady=1)
            var = tk.StringVar(value="–")
            self.detail_labels[key] = var
            tk.Label(meta, textvariable=var, bg=self._colors["panel"], fg=self._colors["fg"], font=(self.cinzel_family, 10, "bold")).grid(row=idx, column=1, sticky="w", pady=1)

        ttk.Label(detail_frame, text="Impact Summary", style="Subtitle.TLabel").grid(row=2, column=0, sticky="w", padx=10, pady=(8, 2))
        self.impact_text = tk.Text(detail_frame, height=4, wrap="word", bg="#0f0f17", fg=self._colors["fg"], insertbackground=self._colors["fg"], highlightthickness=1, highlightbackground=self._colors["accent"], font=(self.cinzel_family, 10))
        self.impact_text.grid(row=3, column=0, sticky="nsew", padx=10)
        self.impact_text.config(state="disabled")

        ttk.Label(detail_frame, text="Raw Analysis (read-only)", style="Subtitle.TLabel").grid(row=4, column=0, sticky="w", padx=10, pady=(8, 2))
        self.raw_json_text = tk.Text(detail_frame, height=6, wrap="word", bg="#0f0f17", fg=self._colors["fg"], insertbackground=self._colors["fg"], highlightthickness=1, highlightbackground=self._colors["accent"], font=(self.cinzel_family, 10))
        self.raw_json_text.grid(row=5, column=0, sticky="nsew", padx=10, pady=(0, 8))
        self.raw_json_text.config(state="disabled")

        ttk.Label(detail_frame, text="Summary (Batch 8 output)", style="Subtitle.TLabel").grid(row=6, column=0, sticky="w", padx=10, pady=(4, 2))
        self.summary_text = tk.Text(detail_frame, height=4, wrap="word", bg="#0f0f17", fg=self._colors["fg"], insertbackground=self._colors["fg"], highlightthickness=1, highlightbackground=self._colors["accent"], font=(self.cinzel_family, 10))
        self.summary_text.grid(row=7, column=0, sticky="nsew", padx=10, pady=(0, 8))
        self.summary_text.config(state="disabled")

        detail_frame.rowconfigure(3, weight=1)
        detail_frame.rowconfigure(5, weight=1)
        detail_frame.rowconfigure(7, weight=1)

        # Activity log pane
        log_frame = self._panel(pw)
        log_frame.columnconfigure(0, weight=1)
        ttk.Label(log_frame, text="Activity Log", style="Section.TLabel").grid(row=0, column=0, sticky="w", padx=10, pady=(8, 4))
        self.log_text = tk.Text(
            log_frame,
            height=8,
            wrap="word",
            bg="#0f0f17",
            fg=self._colors["fg"],
            insertbackground=self._colors["fg"],
            highlightthickness=1,
            highlightbackground=self._colors["accent"],
            font=(self.cinzel_family, 10),
        )
        self.log_text.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 8))
        self.log_text.config(state="disabled")
        log_frame.rowconfigure(1, weight=1)

        pw.add(detail_frame, weight=3)
        pw.add(log_frame, weight=2)

    def _build_header(self) -> None:
        header = tk.Frame(self.center, bg=self._colors["bg"])
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.columnconfigure(0, weight=1)

        title = ttk.Label(header, text=APP_TITLE, style="Title.TLabel")
        title.grid(row=0, column=0, pady=(0, 6))
        title.configure(anchor="center")

        self.logo_label = tk.Label(header, bg=self._colors["bg"])
        self.logo_label.grid(row=1, column=0, pady=(0, 6))
        self._load_logo()

        subtitle = ttk.Label(header, text=APP_SUBTITLE, style="Subtitle.TLabel")
        subtitle.grid(row=2, column=0, pady=(0, 14))
        subtitle.configure(anchor="center")

    def _load_logo(self) -> None:
        if Image is None or ImageTk is None:
            self.logo_label.configure(text="(logo)", fg=self._colors["muted"])
            return

        for c in [
            ASSETS_DIR / "vamp_logo.png",
            ASSETS_DIR / "logo.png",
            HERE / "vamp_logo.png",
            PROJECT_ROOT / "vamp_logo.png",
        ]:
            if c.exists():
                try:
                    img = Image.open(c).convert("RGBA").resize((140, 140))
                    self._logo_img = ImageTk.PhotoImage(img)
                    self.logo_label.configure(image=self._logo_img)
                    return
                except Exception:
                    break
        self.logo_label.configure(text="(logo)", fg=self._colors["muted"])

    def _build_staff_panel(self, row: int) -> None:
        p = self._panel(self.center)
        p.grid(row=row, column=0, sticky="ew", pady=8)
        p.columnconfigure(1, weight=1)

        ttk.Label(p, text="Staff Enrolment & Agreements", style="Section.TLabel").grid(
            row=0, column=0, columnspan=4, sticky="w", padx=12, pady=(10, 6)
        )

        self.staff_id_var = tk.StringVar()
        self.staff_name_var = tk.StringVar()
        self.staff_pos_var = tk.StringVar()
        self.staff_faculty_var = tk.StringVar()
        self.staff_manager_var = tk.StringVar()
        self.staff_year_var = tk.StringVar(value=str(_dt.datetime.now().year))

        def _lbl(text: str, r: int, c: int = 0):
            tk.Label(p, text=text, bg=self._colors["panel"], fg=self._colors["fg"], font=(self.cinzel_family, 10)).grid(
                row=r, column=c, sticky="w", padx=12, pady=4
            )

        def _entry(var: tk.StringVar, r: int, c: int = 1, w: int = 0):
            e = tk.Entry(
                p,
                textvariable=var,
                bg="#0f0f17",
                fg=self._colors["fg"],
                insertbackground=self._colors["fg"],
                highlightthickness=1,
                highlightbackground=self._colors["accent"],
                width=w if w else None,
            )
            e.grid(row=r, column=c, sticky="ew", padx=8, pady=4)

        _lbl("Staff No:", 1)
        _entry(self.staff_id_var, 1)

        _lbl("Full Name:", 2)
        _entry(self.staff_name_var, 2)

        _lbl("Position:", 3)
        _entry(self.staff_pos_var, 3)

        _lbl("Faculty:", 4)
        _entry(self.staff_faculty_var, 4)

        _lbl("Line Manager:", 5)
        _entry(self.staff_manager_var, 5)

        _lbl("Cycle Year:", 6)
        e_year = tk.Entry(
            p,
            textvariable=self.staff_year_var,
            width=10,
            bg="#0f0f17",
            fg=self._colors["fg"],
            insertbackground=self._colors["fg"],
            highlightthickness=1,
            highlightbackground=self._colors["accent"],
        )
        e_year.grid(row=6, column=1, sticky="w", padx=8, pady=4)

        btns = tk.Frame(p, bg=self._colors["panel"])
        btns.grid(row=1, column=3, rowspan=6, sticky="ns", padx=12, pady=4)

        ttk.Button(btns, text="Enroll / Load", command=self._enroll).grid(row=0, column=0, sticky="ew", pady=4)
        ttk.Button(btns, text="Import Task Agreement", command=self._import_ta).grid(row=1, column=0, sticky="ew", pady=4)
        self.generate_skeleton_btn = ttk.Button(btns, text="Generate PA Skeleton", command=self._generate_initial_pa)
        self.generate_skeleton_btn.grid(row=2, column=0, sticky="ew", pady=4)
        ttk.Button(btns, text="Generate PA (AI)", command=self._generate_ai_pa).grid(row=3, column=0, sticky="ew", pady=4)
        self.export_skeleton_btn = ttk.Button(btns, text="Export PA Skeleton", command=self._export_pa_skeleton)
        self.export_skeleton_btn.grid(row=4, column=0, sticky="ew", pady=4)
        ttk.Button(btns, text="Mid-year Review (Jan–Jun)", command=self._generate_midyear).grid(row=5, column=0, sticky="ew", pady=4)
        ttk.Button(btns, text="Final Review (Jul–Oct)", command=self._generate_final).grid(row=6, column=0, sticky="ew", pady=4)
        ttk.Button(btns, text="Open Results Folder", command=lambda: _open_file(OFFLINE_RESULTS_DIR)).grid(row=7, column=0, sticky="ew", pady=4)

        self.staff_status = tk.Label(
            p,
            text="Not enrolled",
            bg=self._colors["panel"],
            fg=self._colors["muted"],
            font=(self.cinzel_family, 10, "italic"),
        )
        self.staff_status.grid(row=7, column=0, columnspan=4, sticky="w", padx=12, pady=(2, 10))

    def _build_expectations_panel(self, row: int) -> None:
        p = self._panel(self.center)
        p.grid(row=row, column=0, sticky="ew", pady=8)
        p.columnconfigure(0, weight=1)

        ttk.Label(p, text="Year Expectations Snapshot (TA/PA)", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", padx=12, pady=(10, 6)
        )

        frame = tk.Frame(p, bg=self._colors["panel"])
        frame.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 10))
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_columnconfigure(1, weight=1)

        left = ttk.LabelFrame(frame, text="Year Expectations", padding=8)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)

        right = ttk.LabelFrame(
            frame, text="KPA Hours/Weight Breakdown + Tasks Summary", padding=8
        )
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)

        self.expectations_text = tk.Text(
            left,
            height=12,
            wrap="word",
            bg="#0f0f17",
            fg=self._colors["fg"],
            insertbackground=self._colors["fg"],
            highlightthickness=1,
            highlightbackground=self._colors["accent"],
            font=(self.cinzel_family, 10),
        )
        self.expectations_text.grid(row=0, column=0, sticky="nsew")
        scroll_left = ttk.Scrollbar(left, orient="vertical", command=self.expectations_text.yview)
        self.expectations_text.configure(yscrollcommand=scroll_left.set)
        scroll_left.grid(row=0, column=1, sticky="ns")
        self.expectations_text.insert("1.0", "Import Task Agreement / Generate PA to populate expectations.")
        self.expectations_text.config(state="disabled")

        self.kpa_breakdown_text = tk.Text(
            right,
            height=12,
            wrap="word",
            bg="#0f0f17",
            fg=self._colors["fg"],
            insertbackground=self._colors["fg"],
            highlightthickness=1,
            highlightbackground=self._colors["accent"],
            font=(self.cinzel_family, 10),
        )
        self.kpa_breakdown_text.grid(row=0, column=0, sticky="nsew")
        scroll_right = ttk.Scrollbar(
            right, orient="vertical", command=self.kpa_breakdown_text.yview
        )
        self.kpa_breakdown_text.configure(yscrollcommand=scroll_right.set)
        scroll_right.grid(row=0, column=1, sticky="ns")
        self.kpa_breakdown_text.insert(
            "1.0", "KPA hours/weighting breakdown will display after TA/PA import."
        )
        self.kpa_breakdown_text.config(state="disabled")

    def _build_scan_panel(self, row: int) -> None:
        p = self._panel(self.center)
        p.grid(row=row, column=0, sticky="ew", pady=8)
        p.columnconfigure(1, weight=1)

        ttk.Label(p, text="Monthly Evidence Scan", style="Section.TLabel").grid(
            row=0, column=0, columnspan=4, sticky="w", padx=12, pady=(10, 6)
        )

        self.folder_var = tk.StringVar(value="(no folder selected)")
        self.month_var = tk.StringVar(value=str(_dt.datetime.now().month))
        self.kpa_var = tk.StringVar(value="AUTO")

        # Ollama scoring toggles
        self.use_ollama_score_var = tk.BooleanVar(value=True)
        self.prefer_llm_rating_var = tk.BooleanVar(value=True)

        tk.Label(p, text="Evidence folder:", bg=self._colors["panel"], fg=self._colors["fg"], font=(self.cinzel_family, 10)).grid(
            row=1, column=0, sticky="w", padx=12, pady=4
        )
        tk.Entry(
            p,
            textvariable=self.folder_var,
            bg="#0f0f17",
            fg=self._colors["fg"],
            insertbackground=self._colors["fg"],
            highlightthickness=1,
            highlightbackground=self._colors["accent"],
        ).grid(row=1, column=1, sticky="ew", padx=8, pady=4)

        ttk.Button(p, text="Choose Folder", command=self._choose_folder).grid(row=1, column=2, padx=8, pady=4)

        tk.Label(p, text="Month:", bg=self._colors["panel"], fg=self._colors["fg"], font=(self.cinzel_family, 10)).grid(
            row=2, column=0, sticky="w", padx=12, pady=4
        )
        ttk.Combobox(p, textvariable=self.month_var, state="readonly", values=[m[0] for m in MONTH_OPTIONS], width=10).grid(
            row=2, column=1, sticky="w", padx=8, pady=4
        )

        tk.Label(p, text="KPA hint:", bg=self._colors["panel"], fg=self._colors["fg"], font=(self.cinzel_family, 10)).grid(
            row=2, column=2, sticky="e", padx=8, pady=4
        )
        ttk.Combobox(p, textvariable=self.kpa_var, state="readonly", values=[k[0] for k in KPA_OPTIONS], width=10).grid(
            row=2, column=3, sticky="w", padx=8, pady=4
        )

        toggles = tk.Frame(p, bg=self._colors["panel"])
        toggles.grid(row=3, column=0, columnspan=4, sticky="ew", padx=12, pady=(6, 0))
        tk.Checkbutton(
            toggles,
            text="Use Ollama contextual scoring (KPA/rating/tier/summary)",
            variable=self.use_ollama_score_var,
            bg=self._colors["panel"],
            fg=self._colors["fg"],
            selectcolor=self._colors["panel"],
            activebackground=self._colors["panel"],
        ).grid(row=0, column=0, sticky="w")

        tk.Checkbutton(
            toggles,
            text="Prefer LLM rating over brain rating (recommended)",
            variable=self.prefer_llm_rating_var,
            bg=self._colors["panel"],
            fg=self._colors["fg"],
            selectcolor=self._colors["panel"],
            activebackground=self._colors["panel"],
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        btnrow = tk.Frame(p, bg=self._colors["panel"])
        btnrow.grid(row=4, column=0, columnspan=4, sticky="ew", padx=12, pady=(6, 12))
        ttk.Button(btnrow, text="Scan Month", command=self._start_scan).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(btnrow, text="Stop", command=self._stop_scan).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(btnrow, text="Export CSV", command=self._export_csv).grid(row=0, column=2, padx=(0, 8))

        self.scan_status = tk.Label(p, text="Idle", bg=self._colors["panel"], fg=self._colors["muted"], font=(self.cinzel_family, 10, "italic"))
        self.scan_status.grid(row=5, column=0, columnspan=4, sticky="w", padx=12, pady=(0, 10))

    def _build_bottom_panes(self) -> None:
        pw = ttk.PanedWindow(self.bottom, orient="vertical")
        pw.grid(row=0, column=0, sticky="nsew")
        self.bottom.rowconfigure(0, weight=1)
        self.bottom.columnconfigure(0, weight=1)

        # ---- Table pane
        table_frame = tk.Frame(self.bottom, bg=self._colors["bg"])
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        table_panel = self._panel(table_frame)
        table_panel.grid(row=0, column=0, sticky="nsew", padx=12, pady=(10, 6))
        table_panel.columnconfigure(0, weight=1)
        table_panel.rowconfigure(1, weight=1)

        ttk.Label(table_panel, text="Scored Evidence (this session)", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", padx=12, pady=(10, 6)
        )

        self.tree = ttk.Treeview(table_panel, columns=TABLE_COLUMNS, show="headings", height=10)
        for c in TABLE_COLUMNS:
            heading = c.replace("_", " ").title()
            width = 120
            if c == "filename":
                width = 220
            elif c in {"brain_notes", "ai_impact"}:
                width = 200
            self.tree.heading(c, text=heading)
            self.tree.column(c, width=width, anchor="w")
        self.tree.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 10))

        yscroll = ttk.Scrollbar(table_panel, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        yscroll.grid(row=1, column=1, sticky="ns", pady=(0, 10))

        # ---- Log pane
        log_frame = tk.Frame(self.bottom, bg=self._colors["bg"])
        log_panel = self._panel(log_frame)
        log_panel.pack(fill="both", expand=True, padx=12, pady=(6, 12))
        log_panel.columnconfigure(0, weight=1)
        log_panel.rowconfigure(1, weight=1)

        ttk.Label(log_panel, text="Activity Log", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", padx=12, pady=(10, 6)
        )

        self.log = tk.Text(
            log_panel,
            height=10,
            wrap="word",
            bg="#0f0f17",
            fg=self._colors["fg"],
            insertbackground=self._colors["fg"],
            highlightthickness=1,
            highlightbackground=self._colors["accent"],
            font=(self.cinzel_family, 10),
        )
        self.log.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 10))
        self.log.config(state="disabled")

        pw.add(table_frame, weight=3)
        pw.add(log_frame, weight=2)

    # ---------------------------
    # Logging / status
    # ---------------------------
    def _drain_ui_queue(self) -> None:
        try:
            while True:
                msg = self.ui_queue.get_nowait()
                kind = msg[0]
                if kind == "row_add":
                    _, row_id, values = msg
                    if hasattr(self, "tree"):
                        self.tree.insert("", "end", iid=row_id, values=values)
                elif kind == "row_update":
                    _, row_id, values = msg
                    if hasattr(self, "tree") and self.tree.exists(row_id):
                        self.tree.item(row_id, values=values)
                elif kind == "log":
                    _, text = msg
                    self._log(text)
                elif kind == "status":
                    _, text = msg
                    self._set_status(text)
                elif kind == "call":
                    fn = msg[1]
                    args = msg[2:]
                    try:
                        fn(*args)
                    except Exception:
                        pass
        except queue.Empty:
            pass
        self.after(80, self._drain_ui_queue)

    def _log(self, msg: str) -> None:
        run_id = getattr(self, "current_run_id", None) or "no-run"

        def _do():
            if not hasattr(self, "log_text"):
                return
            self.log_text.config(state="normal")
            self.log_text.insert("end", f"▶ [{run_id}] [{_now_ts()}] {msg}\n")
            self.log_text.see("end")
            self.log_text.config(state="disabled")
        self.after(0, _do)

    def _set_status(self, msg: str) -> None:
        def _do():
            self.scan_status.configure(text=msg)
        self.after(0, _do)

    def _apply_filters(self, *_args) -> None:
        if not hasattr(self, "tree"):
            return
        status_filter = self.filter_status_var.get()
        kpa_filter = self.filter_kpa_var.get()
        type_filter = self.filter_type_var.get()

        for iid in self.tree.get_children():
            self.tree.delete(iid)

        for row in self.rows:
            if status_filter != "All" and str(row.get("status")) != status_filter:
                continue
            if kpa_filter != "All" and str(row.get("kpa_code")) not in {kpa_filter, row.get("kpa_codes")}:
                continue
            if type_filter != "All" and str(row.get("evidence_type")) != type_filter:
                continue
            detail_id = row.get("detail_id")
            tags = (row.get("status"),)
            values = self._table_values_for_row(row)
            self.tree.insert("", "end", iid=detail_id, values=values, tags=tags)

    def _table_values_for_row(self, row: Dict[str, Any]) -> List[Any]:
        ts = row.get("timestamp") or _now_ts()
        kpa = row.get("kpa_codes") or row.get("kpa_code") or ""
        ai_status = row.get("ai_impact_status")
        if not ai_status:
            ai_status = "OK" if row.get("impact_summary") else (row.get("status_reason") or row.get("status") or "")
        brain_notes = row.get("status_reason") or row.get("kpi_labels") or ""
        return [
            ts,
            row.get("filename", ""),
            kpa,
            row.get("rating", ""),
            row.get("tier_label", ""),
            brain_notes,
            ai_status,
        ]

    def _sort_tree(self, col: str, reverse: bool) -> None:
        if not hasattr(self, "tree"):
            return
        data = []
        for iid in self.tree.get_children(""):
            data.append((self.tree.set(iid, col), iid))
        data.sort(reverse=reverse)
        for index, (_val, iid) in enumerate(data):
            self.tree.move(iid, "", index)
        self.tree.heading(col, command=lambda: self._sort_tree(col, not reverse))

    def _on_row_select(self, _event=None) -> None:
        if not hasattr(self, "tree"):
            return
        selection = self.tree.selection()
        if not selection:
            return
        detail_id = selection[0]
        detail = self.detail_rows.get(detail_id)
        if detail:
            self._populate_detail(detail)

    def _populate_detail(self, detail: Dict[str, Any]) -> None:
        row = detail.get("row", {})
        ctx = detail.get("ctx", {})
        for key, var in self.detail_labels.items():
            if key == "Filename":
                var.set(row.get("filename", "–"))
            elif key == "Evidence Type":
                var.set(row.get("evidence_type", "–"))
            elif key == "Status":
                var.set(row.get("status", "–"))
            elif key == "Review Reason":
                reason = row.get("status_reason") or row.get("needs_review_reason") or ctx.get("needs_review_reason")
                var.set(reason or "–")
            elif key == "Final Rating":
                var.set(str(row.get("rating") or "–"))
            elif key == "Final Tier":
                var.set(row.get("tier_label", "–"))
            elif key == "Confidence":
                var.set(f"{row.get('confidence', '')}%" if row.get("confidence") not in {None, ""} else "–")
            elif key == "KPA":
                var.set(row.get("kpa_codes", row.get("kpa_code", "–")))
            elif key == "KPI":
                var.set(row.get("kpi_labels", "–"))

        impact = detail.get("impact") or row.get("impact_summary", "")
        self.impact_text.config(state="normal")
        self.impact_text.delete("1.0", "end")
        self.impact_text.insert("1.0", impact or "–")
        self.impact_text.config(state="disabled")

        self.raw_json_text.config(state="normal")
        self.raw_json_text.delete("1.0", "end")
        try:
            pretty = json.dumps(ctx.get("raw_llm_json", ctx), ensure_ascii=False, indent=2)
        except Exception:
            pretty = str(ctx)
        self.raw_json_text.insert("1.0", pretty or "–")
        self.raw_json_text.config(state="disabled")

    def _update_summary_panel(self) -> None:
        scored = [r for r in self.rows if r.get("status") == "SCORED"]
        lines = ["KPA\tWeight %\tCompletion %\tStatus"]
        kpa_totals: Dict[str, List[Dict[str, Any]]] = {}
        for r in self.rows:
            code = str(r.get("kpa_code") or "").strip() or "Unknown"
            kpa_totals.setdefault(code, []).append(r)
        for code, entries in sorted(kpa_totals.items()):
            total = len(entries)
            scored_ct = len([e for e in entries if e.get("status") == "SCORED"])
            completion = 0 if total == 0 else int((scored_ct / total) * 100)
            lines.append(f"{code}\t–\t{completion}%\t{'OK' if completion else 'Partial Results'}")
        if scored:
            ratings = [float(r.get("rating") or 0) for r in scored if str(r.get("rating")).strip()]
            avg = sum(ratings) / len(ratings) if ratings else 0
            justification = "Deterministic justification: Derived from Batch 8 aggregator inputs where available."
            lines.append("")
            lines.append(f"Final Rating: {avg:.2f}")
            tier = scored[-1].get("tier_label", "")
            lines.append(f"Final Tier: {tier or '–'}")
            lines.append(justification)
        summary_text = "\n".join(lines)
        self.summary_text.config(state="normal")
        self.summary_text.delete("1.0", "end")
        self.summary_text.insert("1.0", summary_text)
        self.summary_text.config(state="disabled")

    # ---------------------------
    # Staff / agreements actions
    # ---------------------------
    def _ensure_profile(self) -> bool:
        if self.profile is None:
            messagebox.showerror("Not enrolled", "Please enroll/load a staff profile first.")
            return False
        return True

    def _enroll(self) -> None:
        staff_id = self.staff_id_var.get().strip()
        name = self.staff_name_var.get().strip() or staff_id
        pos = self.staff_pos_var.get().strip() or "Lecturer"
        faculty = self.staff_faculty_var.get().strip()
        mgr = self.staff_manager_var.get().strip()

        try:
            year = int(self.staff_year_var.get().strip() or _dt.datetime.now().year)
        except Exception:
            year = _dt.datetime.now().year

        if not staff_id:
            messagebox.showerror("Missing", "Please enter a staff number.")
            return

        self.profile = create_or_load_profile(
            staff_id=staff_id,
            name=name,
            position=pos,
            cycle_year=year,
            faculty=faculty,
            line_manager=mgr,
        )
        self.staff_profile = self.profile
        self.contract_validation_errors = []
        self.contract_validation_warnings = []
        self.kpa2_modules = []
        self.task_agreement_path = None
        self.pa_skeleton_path = None
        self.pa_ai_path = None
        self.pa_initial_path = None
        self.pa_mid_path = None
        self.pa_final_path = None
        self.ta_valid = False
        self.pa_skeleton_ready = False
        self.pa_ai_ready = False
        self.ai_enrich_status = "Not started"
        self.staff_status.configure(
            text=f"Enrolled: {self.profile.name} ({self.profile.staff_id}) | {self.profile.position} | {self.profile.cycle_year}"
        )
        self._log(f"✅ Enrolled / loaded profile: {self.profile.staff_id} ({self.profile.name})")
        _play_sound("vamp.wav")
        self._refresh_expectations_snapshot()
        self._refresh_kpa_breakdown()
        self._refresh_button_states()

    def _import_ta(self) -> None:
        if not self._ensure_profile():
            return

        path = filedialog.askopenfilename(
            title="Select Task Agreement (Excel)",
            filetypes=[("Excel files", "*.xlsx *.xlsm *.xls"), ("All files", "*.*")],
        )
        if not path:
            return
        self.task_agreement_path = Path(path)
        self.contract_validation_errors = []
        self.contract_validation_warnings = []
        self.kpa2_modules = []
        self.ta_validation_errors = []
        self.contract = None
        self.pa_skeleton_ready = False
        self.pa_ai_ready = False
        self.pa_skeleton_path = None
        self.pa_ai_path = None
        self.ai_enrich_status = "Awaiting skeleton"
        director_level = staff_is_director_level(self.profile) if self.profile else False

        try:
            if import_task_agreement_excel is not None:
                import_task_agreement_excel(self.profile, self.task_agreement_path)
                self._log("✅ Task Agreement imported into contract profile (KPIs updated).")
            else:
                self._log("⚠️ TA importer not available (backend/contracts/task_agreement_import.py).")
        except Exception as e:
            self._log(f"❌ Task Agreement import failed: {e}")
            self._log(traceback.format_exc())

        # Validate TA structure and capture teaching modules for KPA2 context
        if parse_nwu_ta is not None:
            try:
                ta_contract = parse_nwu_ta(
                    str(self.task_agreement_path), director_level=director_level
                )
                if validate_ta_contract is not None:
                    valid, errors, warnings = validate_ta_contract(
                        ta_contract, director_level=director_level
                    )
                    self.contract_validation_errors = list(errors)
                    self.contract_validation_warnings = list(warnings)
                    if not valid and getattr(ta_contract, "status", "OK") != "INVALID_TA":
                        self.contract_validation_errors.append("TA failed validation checks")
                else:
                    self.contract_validation_errors = list(
                        getattr(ta_contract, "validation_errors", []) or []
                    )
                    if getattr(ta_contract, "status", "OK") == "INVALID_TA":
                        self.contract_validation_errors.append("TA marked invalid")
                if self.contract_validation_errors:
                    self._log(
                        "❌ TA validation failed: "
                        + "; ".join(self.contract_validation_errors)
                    )
                elif self.contract_validation_warnings:
                    self._log(
                        "⚠️ TA warnings: " + "; ".join(self.contract_validation_warnings)
                    )
                else:
                    self._log("✅ TA validation passed.")
                # Propagate hours/weights/context into the profile for visibility
                if self.profile is not None:
                    kpa_map = {k.code: k for k in self.profile.kpas}
                    for code, kpa_data in getattr(ta_contract, "kpas", {}).items():
                        if code in kpa_map:
                            kpa_map[code].hours = getattr(kpa_data, "hours", None)
                            kpa_map[code].weight = getattr(kpa_data, "weight_pct", None)
                            ctx = getattr(kpa_data, "context", {}) or {}
                            if isinstance(ctx, dict):
                                kpa_map[code].context = ctx
                            if code == "KPA2":
                                self.kpa2_modules = list(ctx.get("modules", [])) if isinstance(ctx, dict) else []
                    self.profile.save()
            except Exception as e:
                self.contract_validation_errors.append(f"TA parse failed: {e}")
                self._log(f"❌ TA validation failed: {e}")

        if parse_task_agreement is not None and not self.kpa2_modules:
            try:
                summary = parse_task_agreement(
                    str(self.task_agreement_path), director_level=director_level
                ) or {}
                modules = summary.get("teaching_modules") or []
                if modules:
                    self.kpa2_modules = list(modules)
                    if self.profile is not None:
                        for k in self.profile.kpas:
                            if k.code == "KPA2":
                                k.context = k.context or {}
                                k.context["modules"] = list(modules)
                        self.profile.save()
            except Exception:
                pass

        # Build expectations JSON (used by Ollama prompt + UI snapshot)
        self._rebuild_expectations()
        _play_sound("vamp.wav")
        self._refresh_expectations_snapshot()
        self._refresh_kpa_breakdown()
        # Construct contract dict for UI breakdowns
        contract_kpas: List[Dict[str, Any]] = []
        if "ta_contract" in locals():
            raw_kpas = getattr(locals()["ta_contract"], "kpas", {}) or {}
            for code, kpa_obj in raw_kpas.items():
                contract_kpas.append(
                    {
                        "code": code,
                        "weight_pct": getattr(kpa_obj, "weight_pct", 0),
                        "hours": getattr(kpa_obj, "hours", 0),
                        "context": getattr(kpa_obj, "context", {}) or {},
                        "flags": getattr(kpa_obj, "flags", []) or [],
                    }
                )
        self.contract = {
            "status": getattr(locals().get("ta_contract", None), "status", None),
            "flags": getattr(locals().get("ta_contract", None), "flags", []) or [],
            "validation_errors": list(self.contract_validation_errors),
            "kpas": contract_kpas,
        }
        self.ta_validation_errors = list(self.contract_validation_errors)
        self.ta_valid = not self.ta_validation_errors and (self.contract.get("status") != "INVALID_TA")
        self._render_contract_health()
        self._render_kpa_breakdown_table()
        self._refresh_button_states()
        self._update_stage_label()
        if self.ta_validation_errors:
            messagebox.showerror("Contract invalid", "; ".join(self.ta_validation_errors))
        else:
            self._log("TA imported")

    def _generate_initial_pa(self) -> None:
        self._generate_pa_skeleton()

    def _generate_ai_pa(self) -> None:
        self._generate_pa_ai()

    def _generate_pa_skeleton(self) -> None:
        if not self._ensure_profile():
            return
        if not self.ta_valid:
            messagebox.showerror("TA invalid", "Import a valid Task Agreement before generating the PA skeleton.")
            return
        try:
            if generate_pa_skeleton_from_ta is None:
                raise RuntimeError("backend/contracts/pa_generator.py not available")
            out, rows = generate_pa_skeleton_from_ta(self.profile, OFFLINE_RESULTS_DIR)
            self.pa_skeleton_path = Path(out)
            self.pa_skeleton_ready = True
            self.pa_ai_ready = False
            self.pa_ai_path = None
            self.ai_enrich_status = "Skeleton ready"
            # Keep initial path pointing to the skeleton until AI enrichment replaces it.
            self.pa_initial_path = self.pa_initial_path or self.pa_skeleton_path
            self.pa_skeleton_rows = list(rows or [])
            self.session_state["pa_skeleton_rows"] = list(rows or [])
            self.session_state["pa_skeleton_path"] = str(self.pa_skeleton_path)
            self._log("PA skeleton generated")
            self._log(f"✅ PA skeleton generated at: {self.pa_skeleton_path}")
        except Exception as e:
            self.pa_skeleton_ready = False
            self.ai_enrich_status = "Awaiting skeleton"
            self._log(f"❌ Error generating PA skeleton: {e}")
            self._log(traceback.format_exc())
        self._rebuild_expectations()
        _play_sound("vamp.wav")
        self._refresh_expectations_snapshot()
        self._refresh_kpa_breakdown()
        self._render_contract_health()
        self._refresh_button_states()

    def _generate_pa_ai(self) -> None:
        if enrich_pa_with_ai is None:
            messagebox.showerror("AI not available", "backend/contracts/pa_enricher_ai.py could not be loaded.")
            return
        if not self._ensure_profile():
            return
        if not self.pa_skeleton_rows:
            self.ai_enrich_status = "Awaiting skeleton"
            self._refresh_button_states()
            messagebox.showwarning(
                "PA skeleton required",
                "Generate the PA skeleton before requesting AI enrichment.",
            )
            return

        self.ai_enrich_running = True
        self.pa_ai_ready = False
        self.ai_enrich_status = "In progress"
        self._refresh_button_states()

        def _worker() -> None:
            log_messages: List[str] = []
            status_message = "AI enrichment complete"
            success = False
            try:
                self.ui_queue.put(("status", "Contacting AI for PA enrichment…"))
                self.ui_queue.put(("log", "Contacting AI for PA enrichment…"))
                enrich_pa_with_ai(self.profile, self.pa_skeleton_rows)
                if generate_initial_pa is None:
                    raise RuntimeError("backend/contracts/pa_excel.py not available")
                out = generate_initial_pa(self.profile, OFFLINE_RESULTS_DIR)
                self.pa_initial_path = Path(out)
                self.pa_ai_path = Path(out)
                self.session_state["pa_initial_path"] = str(self.pa_initial_path)
                log_messages.append("AI PA generated")
                log_messages.append(f"✅ AI-enriched PA generated at: {self.pa_initial_path}")
                status_message = "AI enrichment complete"
                success = True
            except Exception as e:
                timeout_exceptions: Tuple[type, ...] = ()
                if requests is not None:
                    timeout_exceptions = (
                        requests.Timeout,
                        requests.exceptions.Timeout,
                        requests.exceptions.ReadTimeout,
                        requests.exceptions.ConnectTimeout,
                    )

                timeout_like = (
                    isinstance(e, timeout_exceptions) if timeout_exceptions else False
                ) or "timeout" in str(e).lower()
                if timeout_like:
                    status_message = "Timeout — manual edit required"
                    log_messages.append("⚠️ AI enrichment timed out—manual edit required")
                else:
                    status_message = "AI enrichment failed—manual edit required"
                    log_messages.append("AI enrichment failed—manual edit required")
                    log_messages.append(f"❌ AI enrichment error: {e}")
            finally:
                self.after(
                    0,
                    lambda: self._finalize_ai_enrichment(
                        status_message,
                        log_messages,
                        success,
                    ),
                )

        threading.Thread(target=_worker, daemon=True).start()

    def _finalize_ai_enrichment(
        self, status_message: str, log_messages: List[str], success: bool
    ) -> None:
        for msg in log_messages:
            self._log(msg)
        self._set_status(status_message)
        self.pa_ai_ready = success
        self.ai_enrich_status = status_message
        if not success:
            self.pa_ai_path = None
        self.ai_enrich_running = False
        self._rebuild_expectations()
        _play_sound("vamp.wav")
        self._refresh_expectations_snapshot()
        self._refresh_kpa_breakdown()
        self._render_contract_health()
        self._refresh_button_states()

    def _export_pa_excel(self) -> None:
        if not self.pa_skeleton_ready:
            messagebox.showwarning("Generate PA", "Generate the PA skeleton before exporting.")
            return
        if not self.pa_ai_ready:
            messagebox.showwarning(
                "AI enrichment pending",
                "Run AI enrichment first, or use 'Export PA Skeleton' to export the draft.",
            )
            return
        path_to_open = self.pa_ai_path if self.pa_ai_ready and self.pa_ai_path else self.pa_skeleton_path
        if not path_to_open:
            messagebox.showerror("Missing PA", "No PA path available to export.")
            return
        _open_file(path_to_open)
        self._log("PA exported" if not self.pa_ai_ready else "AI PA exported")
        self._refresh_button_states()

    def _export_pa_skeleton(self) -> None:
        if not self._ensure_profile():
            return
        self._update_contract_status()
        if self.contract_validation_errors:
            messagebox.showerror("Contract invalid", self.contract_status_reason)
            return
        if self.pa_skeleton_path and self.pa_skeleton_path.exists():
            _open_file(self.pa_skeleton_path)
            return
        self._generate_initial_pa()
        if self.pa_skeleton_path and self.pa_skeleton_path.exists():
            _open_file(self.pa_skeleton_path)

    def _generate_midyear(self) -> None:
        if not self._ensure_profile():
            return
        try:
            if generate_mid_year_review is None:
                raise RuntimeError("backend/contracts/pa_excel.py not available")
            out = generate_mid_year_review(self.profile, OFFLINE_RESULTS_DIR)
            self.pa_mid_path = Path(out)
            self._log(f"✅ Mid-year review generated at: {self.pa_mid_path}")
        except Exception as e:
            self._log(f"❌ Error generating Mid-year review: {e}")
            self._log(traceback.format_exc())
        self._rebuild_expectations()
        _play_sound("vamp.wav")
        self._refresh_expectations_snapshot()
        self._refresh_kpa_breakdown()

    def _generate_final(self) -> None:
        if not self._ensure_profile():
            return
        try:
            if generate_final_review is None:
                raise RuntimeError("backend/contracts/pa_excel.py not available")
            out = generate_final_review(self.profile, OFFLINE_RESULTS_DIR)
            self.pa_final_path = Path(out)
            self._log(f"✅ Final review generated at: {self.pa_final_path}")
        except Exception as e:
            self._log(f"❌ Error generating Final review: {e}")
            self._log(traceback.format_exc())
        self._rebuild_expectations()
        _play_sound("vamp.wav")
        self._refresh_expectations_snapshot()
        self._refresh_kpa_breakdown()

    def _rebuild_expectations(self) -> None:
        if not self._ensure_profile():
            return
        if not callable(build_staff_expectations):
            self._log(
                "ℹ️ Expectations engine not installed; using TA->Profile summary only."
            )
            self.expectations = self._summary_from_profile_only()
            return
        if not self.task_agreement_path:
            # It's okay: user might have a PA but no TA yet; we still can attempt with None.
            self._log("ℹ️ No Task Agreement selected yet – expectations will be limited.")
        try:
            ta_path = str(self.task_agreement_path) if self.task_agreement_path else ""
            pa_path_obj = self.pa_initial_path or self.pa_skeleton_path
            pa_path = str(pa_path_obj) if pa_path_obj else None
            exp = build_staff_expectations(self.profile.staff_id, ta_path, pa_path)
            self.expectations = exp or {}
            self._log("✅ Expectations JSON rebuilt (for contextual scoring).")
        except Exception as e:
            self._log(f"⚠️ Could not rebuild expectations: {e}")
            self.expectations = self._summary_from_profile_only()

    def _summary_from_profile_only(self) -> dict:
        p = self.staff_profile
        if not p:
            return {}
        kpa_summary: Dict[str, Any] = {}
        for k in p.kpas:
            kpa_summary[f"{k.code} – {k.name}"] = {
                "weight": k.weight,
                "hours": k.hours,
                "key_expectations": [kpi.description for kpi in (k.kpis or [])][:12],
            }
        return {"kpa_summary": kpa_summary}

    def _refresh_expectations_snapshot(self) -> None:
        snap = ""
        if self.profile:
            if callable(load_staff_expectations):
                try:
                    self.expectations = load_staff_expectations(self.profile.staff_id) or {}
                    # Compact friendly snapshot (not full raw)
                    snap = json.dumps(self.expectations, ensure_ascii=False, indent=2)[:6000]
                except Exception as e:
                    snap = f"(Could not load expectations: {e})"
            else:
                self._log(
                    "ℹ️ Expectations engine not installed; TA summary will still display once TA is imported."
                )
                if not self.expectations:
                    self.expectations = self._summary_from_profile_only()
                snap = (
                    json.dumps(self.expectations, ensure_ascii=False, indent=2)[:6000]
                    if self.expectations
                    else "Import Task Agreement / Generate PA to populate expectations."
                )
        else:
            snap = "Import Task Agreement / Generate PA to populate expectations."

        if hasattr(self, "expectations_text"):
            self.expectations_text.config(state="normal")
            self.expectations_text.delete("1.0", "end")
            self.expectations_text.insert("1.0", snap)
            self.expectations_text.config(state="disabled")
        self._render_kpa_breakdown(self.expectations)

    def _render_kpa_breakdown(self, summary: Optional[Dict[str, Any]]) -> None:
        if not hasattr(self, "kpa_breakdown_text"):
            return

        kpa_summary: Dict[str, Any] = {}
        if isinstance(summary, dict):
            kpa_summary = summary.get("kpa_summary") or {}

        if not kpa_summary and self.profile:
            self.expectations = self.expectations or self._summary_from_profile_only()
            kpa_summary = self.expectations.get("kpa_summary") or {}


        if not kpa_summary and self.profile:
            self.expectations = self.expectations or self._summary_from_profile_only()
            kpa_summary = self.expectations.get("kpa_summary") or {}

        lines: List[str] = []
        for kpa_label, details in kpa_summary.items():
            weight = details.get("weight", "–") if isinstance(details, dict) else "–"
            hours = details.get("hours", "–") if isinstance(details, dict) else "–"
            try:
                weight = f"{float(weight):.2f}"
            except Exception:
                weight = weight or "–"
            try:
                hours = f"{float(hours):.2f}"
            except Exception:
                hours = hours or "–"

            lines.append(f"{kpa_label}")
            lines.append(f"  Hours: {hours} | Weight: {weight}%")

            tasks = []
            if isinstance(details, dict):
                tasks = (details.get("key_expectations") or details.get("tasks") or [])
            if tasks:
                lines.append("  Tasks extracted (top 10):")
                for task in tasks[:10]:
                    lines.append(f"   • {task}")
            else:
                lines.append("  Tasks extracted (top 10): –")
            lines.append("")

        if not lines:
            lines.append("KPA hours/weighting breakdown will display after TA/PA import.")

        self.kpa_breakdown_text.config(state="normal")
        self.kpa_breakdown_text.delete("1.0", "end")
        self.kpa_breakdown_text.insert("1.0", "\n".join(lines))
        self.kpa_breakdown_text.config(state="disabled")

    def _refresh_kpa_breakdown(self) -> None:
        if hasattr(self, "kpa_health_tree"):
            for iid in self.kpa_health_tree.get_children():
                self.kpa_health_tree.delete(iid)
        profile = self.profile
        kpas = profile.kpas if profile else []
        director_level = staff_is_director_level(profile) if profile else False
        code_order = [f"KPA{i}" for i in range(1, 6)]
        if director_level:
            code_order.append("KPA6")
        kpa_lookup = {k.code: k for k in (kpas or [])}
        for code in code_order:
            kpa = kpa_lookup.get(code)
            name = getattr(kpa, "name", "") or f"{code}"
            hours = getattr(kpa, "hours", None)
            weight = getattr(kpa, "weight", None)
            status = "Missing"
            if hours is not None and weight is not None and float(hours or 0) > 0 and float(weight or 0) > 0:
                status = "OK"
            elif hours or weight:
                status = "Needs Review"
            if hasattr(self, "kpa_health_tree"):
                self.kpa_health_tree.insert(
                    "",
                    "end",
                    values=[code, name, hours if hours is not None else "–", weight if weight is not None else "–", status],
                )
        modules = list(self.kpa2_modules)
        if not modules and kpa_lookup.get("KPA2"):
            context = getattr(kpa_lookup.get("KPA2"), "context", {}) or {}
            if isinstance(context, dict):
                modules = list(context.get("modules") or [])
        if hasattr(self, "modules_var"):
            if modules:
                self.modules_var.set("Teaching modules: " + "; ".join(modules))
            else:
                self.modules_var.set("Teaching modules: –")
        self._render_kpa_breakdown(self.expectations)
        self._update_contract_status()

    def _update_contract_status(self) -> None:
        profile = self.profile
        if profile is None:
            self.contract_status_var.set("❌ No Contract")
            self.contract_status_reason = "No valid Task/Performance Agreement loaded."
            self.start_btn.state(["disabled"])
            self._refresh_action_states()
            return
        kpas = profile.kpas or []
        missing = [k for k in kpas if not (getattr(k, "hours", 0) and getattr(k, "weight", 0))]
        if self.contract_validation_errors:
            self.contract_status_var.set("❌ Contract Invalid")
            self.contract_status_reason = "; ".join(self.contract_validation_errors)
            self.start_btn.state(["disabled"])
        elif missing:
            self.contract_status_var.set("⚠️ Contract Incomplete")
            self.contract_status_reason = "KPAs are missing hours/weights. Add them in the contract before scanning."
            self.start_btn.state(["disabled"])
        else:
            self.contract_status_var.set("✅ Contract Loaded")
            if self.contract_validation_warnings:
                self.contract_status_reason = "; ".join(self.contract_validation_warnings)
            else:
                self.contract_status_reason = "All KPAs have hours and weights."
            self.start_btn.state(["!disabled"])
        self._refresh_action_states()
        self._render_contract_health()
        self._refresh_button_states()

    def _render_contract_health(self) -> None:
        status = "INVALID_TA"
        if self.ta_valid and not self.pa_skeleton_ready:
            status = "VALID_TA_ONLY"
        elif self.pa_skeleton_ready and not self.pa_ai_ready:
            status = "VALID_TA_WITH_SKELETON"
        elif self.pa_ai_ready:
            status = "VALID_TA_WITH_AI_PA"
        if hasattr(self, "lbl_contract_status"):
            self.lbl_contract_status.configure(text=f"Contract: {status}")

        flags: List[str] = []
        if self.contract and self.contract.get("flags"):
            for f in self.contract["flags"]:
                flags.append(f.get("code", "FLAG"))
        if hasattr(self, "lbl_flags"):
            self.lbl_flags.configure(text=("Flags: " + ", ".join(flags)) if flags else "Flags: none")

    def _refresh_action_states(self) -> None:
        """Synchronise button states with contract/scanning readiness."""

        if hasattr(self, "start_btn"):
            if self.contract_validation_errors:
                self.start_btn.state(["disabled"])

        if hasattr(self, "generate_skeleton_btn"):
            if self.contract_validation_errors:
                self.generate_skeleton_btn.state(["disabled"])
            else:
                self.generate_skeleton_btn.state(["!disabled"])

        if hasattr(self, "export_skeleton_btn"):
            if self.contract_validation_errors:
                self.export_skeleton_btn.state(["disabled"])
            else:
                self.export_skeleton_btn.state(["!disabled"])

        if hasattr(self, "export_pa_btn"):
            # Disable export when Batch 8-style summaries are incomplete
            if self.contract_validation_errors or not self.rows or any(r.get("status") != "SCORED" for r in self.rows):
                self.export_pa_btn.state(["disabled"])
            else:
                self.export_pa_btn.state(["!disabled"])

    def _show_contract_tooltip(self) -> None:
        messagebox.showinfo("Contract status", self.contract_status_reason)

    # ---------------------------
    # Folder / scan actions
    # ---------------------------
    def _choose_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select evidence folder")
        if not folder:
            return
        self.current_evidence_folder = Path(folder)
        self.evidence_folder = self.current_evidence_folder
        self.folder_var.set(str(self.current_evidence_folder))
        self._log(f"📁 Selected evidence folder: {self.current_evidence_folder}")
        self._refresh_button_states()

    def _get_kpa_hint_code(self) -> Optional[str]:
        label = (self.kpa_var.get() or "").strip().upper()
        if label in {"KPA1", "KPA2", "KPA3", "KPA4", "KPA5"}:
            return label
        return None

    def _start_scan(self) -> None:
        if not self._ensure_profile():
            return
        self._update_contract_status()
        status_text = self.contract_status_var.get()
        if status_text.startswith("❌"):
            messagebox.showerror("Contract invalid", self.contract_status_reason)
            return
        if status_text.startswith("⚠️"):
            messagebox.showwarning("Contract incomplete", self.contract_status_reason)
            return
        if self.current_evidence_folder is None or not self.current_evidence_folder.exists():
            messagebox.showerror("Missing folder", "Please choose an evidence folder.")
            return
        if self._scan_thread and self._scan_thread.is_alive():
            messagebox.showinfo("Scan running", "A scan is already running.")
            return

        self.current_run_id = generate_run_id()
        self._stop_flag.clear()
        self._set_status("Scanning...")
        self._log(f"⏳ Starting scan... run_id={self.current_run_id}")
        _play_sound("vamp.wav")

        self.scan_running = True
        self._refresh_button_states()

        self._scan_thread = threading.Thread(target=self._scan_worker, daemon=True)
        self._scan_thread.start()

    def _stop_scan(self) -> None:
        self._stop_flag.set()
        self._set_status("Stopping...")
        self._log("🛑 Stop requested. Finishing current item...")
        self.scan_running = False
        self._refresh_button_states()

    # ---------------------------
    # Contract context builder
    # ---------------------------
    def _build_contract_context(self) -> str:
        """
        This is the text we feed to the LLM alongside the evidence snippet.
        Keep it short, staff-specific, and high-signal.
        """
        parts: List[str] = []

        # 1) Staff contract KPAs/KPIs
        if self.profile is not None:
            parts.append(
                f"STAFF CONTRACT (staff={self.profile.staff_id}, year={self.profile.cycle_year}, position={self.profile.position}):"
            )
            for kpa in (self.profile.kpas or []):
                kpa_line = f"- {kpa.code}: {kpa.name}"
                if kpa.weight is not None:
                    kpa_line += f" | weight={kpa.weight}"
                if kpa.hours is not None:
                    kpa_line += f" | hours={kpa.hours}"
                parts.append(kpa_line)
                kpa_context = getattr(kpa, "context", {}) or {}
                if kpa.code == "KPA2":
                    modules = kpa_context.get("modules") or self.kpa2_modules
                    if modules:
                        parts.append("  • Modules: " + ", ".join(modules))
                # Show top few KPIs as anchors (avoid huge prompts)
                for kpi in (kpa.kpis or [])[:6]:
                    desc = (kpi.description or "").strip()
                    outs = (kpi.outputs or "").strip()
                    if not desc and not outs:
                        continue
                    bullet = "  • " + (desc or outs)
                    if outs and desc and outs != desc:
                        bullet += f" (outputs: {outs})"
                    parts.append(bullet)

        # 2) Policy/guideline snippets (optional)
        for p in [DATA_DIR / "kpa_guidelines.md", DATA_DIR / "policy_playbook.md"]:
            if p.exists():
                try:
                    txt = p.read_text(encoding="utf-8", errors="ignore")
                    parts.append(f"[{p.name}] " + txt[:900])
                except Exception:
                    pass

        return "\n".join(parts).strip()

    # ---------------------------
    # Scan worker
    # ---------------------------
    def _scan_worker(self) -> None:
        try:
            root = Path(self.folder_var.get())
            if not root.is_dir():
                self._log(f"❌ Evidence folder does not exist: {root}")
                self._set_status("Idle")
                return

            profile = self.profile
            assert profile is not None

            try:
                year = int(self.staff_year_var.get().strip() or profile.cycle_year)
            except Exception:
                year = profile.cycle_year

            try:
                month_int = int(self.month_var.get().strip())
                if not (1 <= month_int <= 12):
                    raise ValueError
            except Exception:
                month_int = _dt.datetime.now().month

            month_bucket = f"{year}-{month_int:02d}"
            contract_context = self._build_contract_context()
            kpa_hint = self._get_kpa_hint_code()

            # Collect artefacts
            artefacts: List[Path] = []
            if ingest_paths is not None:
                try:
                    objs = ingest_paths(root, None, None)  # type: ignore
                    artefacts = [o.path for o in objs if getattr(o, "path", None)]
                except Exception:
                    artefacts = []
            if not artefacts:
                # Fallback: scan common evidence file types
                exts = {".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls", ".xlsm", ".txt", ".png", ".jpg", ".jpeg", ".eml", ".msg"}
                for p in root.rglob("*"):
                    if p.is_file() and p.suffix.lower() in exts:
                        artefacts.append(p)
                artefacts.sort()

            # Reset UI
            self.rows.clear()
            self.detail_rows.clear()
            self._detail_counter = 0
            self.after(0, lambda: self.tree.delete(*self.tree.get_children()))
            self._refresh_action_states()
            self._log(f"🔎 Starting scan of {len(artefacts)} artefacts for month {month_bucket}…")

            for path in artefacts:
                if self._stop_flag.is_set():
                    self._log("🛑 Scan stopped by user.")
                    break

                timestamp = _now_ts()
                self._detail_counter += 1
                detail_id = f"row-{self._detail_counter}"
                placeholder = {
                    "timestamp": timestamp,
                    "filename": path.name,
                    "kpa_code": "",
                    "rating": "…",
                    "tier_label": "…",
                    "status_reason": "Scoring…",
                    "ai_impact_status": "…",
                }
                self.ui_queue.put(("row_add", detail_id, self._table_values_for_row(placeholder)))

                use_ollama = bool(self.use_ollama_score_var.get())
                prefer_llm_rating = bool(self.prefer_llm_rating_var.get())
                row, ctx, impact = process_artefact(
                    path=path,
                    month_bucket=month_bucket,
                    run_id=self.current_run_id,
                    profile=profile,
                    contract_context=contract_context,
                    kpa_hint=kpa_hint or "",
                    use_ollama=use_ollama,
                    prefer_llm_rating=prefer_llm_rating,
                    log=self._log,
                    extract_fn=extract_text_for,
                    contextual_fn=contextual_score,
                    brain_fn=brain_score_evidence,
                )

                row["timestamp"] = timestamp
                row["detail_id"] = detail_id
                self.rows.append(row)
                detail = {"row": row, "ctx": ctx, "impact": impact}
                self.detail_rows[detail_id] = detail
                interim = dict(row)
                interim["ai_impact_status"] = "…"
                self.ui_queue.put(("row_update", detail_id, self._table_values_for_row(interim)))
                ai_status = ctx.get("llm_status") or ("OK" if impact else row.get("status_reason") or row.get("status", ""))
                row["ai_impact_status"] = ai_status
                self.ui_queue.put(("row_update", detail_id, self._table_values_for_row(row)))

                if impact:
                    self._log(f"{path.name} → {impact}")
                else:
                    reason = row.get("status_reason") or row.get("status")
                    self._log(f"{path.name} → {reason or '(no impact summary)'}")

                # 5) Persist detailed evidence row (longitudinal log)
                if append_evidence_row is not None:
                    try:
                        values_hits = ctx.get("values_hits", [])
                        if isinstance(values_hits, list):
                            values_hits_str = ", ".join(str(v) for v in values_hits)
                        else:
                            values_hits_str = str(values_hits)

                        raw_llm_json = ctx.get("raw_llm_json", {})
                        try:
                            raw_llm_json_str = json.dumps(raw_llm_json, ensure_ascii=False)
                        except Exception:
                            raw_llm_json_str = str(raw_llm_json)

                        evidence_row = {
                            "staff_id": profile.staff_id,
                            "cycle_year": profile.cycle_year,
                            "month_bucket": month_bucket,
                            "file_path": str(path),
                            "file_name": path.name,
                            "file_sha1": _sha1(path),
                            "kpa_code": row["kpa_code"],
                            "kpa_name": row["kpa_name"],
                            "kpi_id": "",
                            "kpi_description": "",
                            "rating": row["rating"],
                            "rating_label": row["rating_label"],
                            "impact_summary": impact,
                            "risks_or_gaps": "",
                            "values_hits": values_hits_str,
                            "evidence_type": _guess_evidence_type(path),
                            "raw_llm_json": raw_llm_json_str,
                            "run_id": self.current_run_id,
                            "status": row.get("status", ""),
                            "extract_status": row.get("extract_status", ""),
                            "extract_error": row.get("extract_error", ""),
                            "status_reason": row.get("status_reason", ""),
                        }
                        append_evidence_row(profile.staff_id, profile.cycle_year, evidence_row)
                    except Exception as ex:
                        self._log(f"⚠️ Could not write evidence_store row: {ex}")

            # 6) Session CSV summary
            out_path = OFFLINE_RESULTS_DIR / (
                f"contextual_results_{profile.staff_id}_{profile.cycle_year}_{month_bucket}_{self.current_run_id}.csv"
            )
            try:
                with out_path.open("w", newline="", encoding="utf-8") as f:
                    w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
                    w.writeheader()
                    for r in self.rows:
                        w.writerow({k: r.get(k, "") for k in CSV_COLUMNS})
                self._log(f"✅ Contextual results written to: {out_path}")
            except Exception as ex:
                self._log(f"⚠️ Could not write session CSV: {ex}")

            self._set_status("Idle")
            self.scan_running = False
            self._update_summary_panel()
            self._refresh_action_states()
            self._refresh_button_states()
            self._log("✅ Scan complete.")
            _play_sound("vamp.wav")

        except Exception as e:
            self._set_status("Idle")
            self.scan_running = False
            self._log(f"❌ Fatal scan error: {e}")
            self._log(traceback.format_exc())
            self._refresh_button_states()

    # ---------------------------
    # Export CSV (manual)
    # ---------------------------
    def _export_csv(self) -> None:
        if not self._ensure_profile():
            return
        if not self.rows:
            messagebox.showinfo("No data", "No evidence rows to export yet.")
            return

        profile = self.profile
        assert profile is not None

        month_bucket = (self.rows[-1].get("month") or "").strip() or f"{profile.cycle_year}-{int(self.month_var.get() or 0):02d}"
        out = OFFLINE_RESULTS_DIR / f"evidence_summary_{profile.staff_id}_{profile.cycle_year}_{month_bucket}.csv"
        try:
            with out.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
                w.writeheader()
                for r in self.rows:
                    w.writerow({k: r.get(k, "") for k in CSV_COLUMNS})
            self._log(f"✅ Exported: {out}")
            _open_file(out.parent)
        except Exception as e:
            self._log(f"❌ Export error: {e}")


if __name__ == "__main__":
    app = OfflineApp()
    app.mainloop()
