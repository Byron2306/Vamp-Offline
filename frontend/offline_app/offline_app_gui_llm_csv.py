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
import threading
import time
import traceback
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
    from backend.staff_profile import create_or_load_profile, StaffProfile  # type: ignore
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
    from backend.expectation_engine import build_staff_expectations, load_staff_expectations  # type: ignore
except Exception:
    build_staff_expectations = None
    load_staff_expectations = None

try:
    from backend.vamp_master import generate_run_id, ingest_paths, extract_text_for  # type: ignore
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
    "file",
    "month",
    "kpa_code",
    "kpa_name",
    "rating",
    "rating_label",
    "tier_label",
    "status",
]

CSV_COLUMNS = [
    "run_id",
    "filename",
    "file_path",
    "file",
    "month",
    "kpa_code",
    "kpa_name",
    "rating",
    "rating_label",
    "tier_label",
    "status",
    "extract_status",
    "extract_error",
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

    if extract_fn is None:
        extract_status = "failed"
        extract_error = "text extractor unavailable"
        logger(f"{path.name} → ❌ Failed to extract text: {extract_error}")
    else:
        try:
            extracted_text = extract_fn(path) or ""
            if not extracted_text.strip():
                extract_status = "empty"
                extract_error = "no text extracted"
        except Exception as e:
            extract_status = "failed"
            extract_error = str(e)
            logger(f"{path.name} → ❌ Failed to extract text: {e}")

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
                logger(f"{path.name} → ❌ Brain scoring error: {ex}")
        ctx = _normalize_ctx(ctx, kpa_hint)
    else:
        ctx = _normalize_ctx(ctx, kpa_hint)

    if extract_status != "ok" or scoring_error:
        status = "needs_review"
    elif scoring_available:
        status = "scored"
    else:
        status = "unscorable"

    row = {
        "run_id": run_id,
        "filename": path.name,
        "file_path": str(path),
        "file": path.name,
        "month": month_bucket,
        "kpa_code": str(ctx.get("primary_kpa_code") or "").strip(),
        "kpa_name": str(ctx.get("primary_kpa_name") or "").strip() or "Unknown",
        "rating": "" if ctx.get("rating") is None else ctx.get("rating"),
        "rating_label": str(ctx.get("rating_label") or "").strip() or "Unrated",
        "tier_label": str(ctx.get("tier_label") or "").strip() or "Developmental",
        "status": status,
        "extract_status": extract_status,
        "extract_error": extract_error,
    }
    impact = (ctx.get("impact_summary") or ctx.get("contextual_response") or "").strip()
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
        self.task_agreement_path: Optional[Path] = None
        self.pa_initial_path: Optional[Path] = None
        self.pa_mid_path: Optional[Path] = None
        self.pa_final_path: Optional[Path] = None
        self.current_evidence_folder: Optional[Path] = None

        self.expectations: Dict[str, Any] = {}
        self.rows: List[Dict[str, Any]] = []

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

        # Layout: two rows
        self.configure(bg=self._colors["bg"])
        self.outer = tk.Frame(self, bg=self._colors["bg"])
        self.outer.grid(row=0, column=0, sticky="nsew")
        self.bottom = tk.Frame(self, bg=self._colors["bg"])
        self.bottom.grid(row=1, column=0, sticky="nsew")

        self.rowconfigure(0, weight=0)
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        self._build_scrollable_top()
        self._build_bottom_panes()

        self.bind("<Escape>", lambda e: self._stop_scan())

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

    # ---------------------------
    # UI builders
    # ---------------------------
    def _build_scrollable_top(self) -> None:
        bg = self._colors["bg"]
        canvas = tk.Canvas(self.outer, bg=bg, highlightthickness=0)
        vbar = ttk.Scrollbar(self.outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vbar.set)

        canvas.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")
        self.outer.columnconfigure(0, weight=1)
        self.outer.rowconfigure(0, weight=1)

        self.top_frame = tk.Frame(canvas, bg=bg)
        self._top_window = canvas.create_window((0, 0), window=self.top_frame, anchor="n")

        def _on_configure(_event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(event):
            canvas.itemconfig(self._top_window, width=event.width)

        self.top_frame.bind("<Configure>", _on_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(event):
            # Windows: delta in ±120
            delta = -1 * int(event.delta / 120) if event.delta else 0
            canvas.yview_scroll(delta, "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        self.center = tk.Frame(self.top_frame, bg=bg)
        self.center.grid(row=0, column=0, sticky="nsew", padx=24, pady=16)
        self.top_frame.columnconfigure(0, weight=1)

        self._build_header()
        self._build_staff_panel(row=1)
        self._build_expectations_panel(row=2)
        self._build_scan_panel(row=3)

    def _panel(self, parent) -> tk.Frame:
        f = tk.Frame(parent, bg=self._colors["panel"], highlightthickness=1, highlightbackground=self._colors["line"])
        return f

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
        ttk.Button(btns, text="Generate Initial PA", command=self._generate_initial_pa).grid(row=2, column=0, sticky="ew", pady=4)
        ttk.Button(btns, text="Mid-year Review (Jan–Jun)", command=self._generate_midyear).grid(row=3, column=0, sticky="ew", pady=4)
        ttk.Button(btns, text="Final Review (Jul–Oct)", command=self._generate_final).grid(row=4, column=0, sticky="ew", pady=4)
        ttk.Button(btns, text="Open Results Folder", command=lambda: _open_file(OFFLINE_RESULTS_DIR)).grid(row=5, column=0, sticky="ew", pady=4)

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

        self.expectations_text = tk.Text(
            p,
            height=9,
            wrap="word",
            bg="#0f0f17",
            fg=self._colors["fg"],
            insertbackground=self._colors["fg"],
            highlightthickness=1,
            highlightbackground=self._colors["accent"],
            font=(self.cinzel_family, 10),
        )
        self.expectations_text.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 10))
        self.expectations_text.insert("1.0", "Import Task Agreement / Generate PA to populate expectations.")
        self.expectations_text.config(state="disabled")

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
        table_panel = self._panel(table_frame)
        table_panel.pack(fill="both", expand=True, padx=12, pady=(10, 6))
        table_panel.columnconfigure(0, weight=1)
        table_panel.rowconfigure(1, weight=1)

        ttk.Label(table_panel, text="Scored Evidence (this session)", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", padx=12, pady=(10, 6)
        )

        self.tree = ttk.Treeview(table_panel, columns=TABLE_COLUMNS, show="headings", height=10)
        for c in TABLE_COLUMNS:
            self.tree.heading(c, text=c.replace("_", " ").title())
            self.tree.column(c, width=140 if c != "file" else 260, anchor="w")
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
    def _log(self, msg: str) -> None:
        run_id = getattr(self, "current_run_id", None) or "no-run"

        def _do():
            self.log.config(state="normal")
            self.log.insert("end", f"▶ [{run_id}] [{_now_ts()}] {msg}\n")
            self.log.see("end")
            self.log.config(state="disabled")
        self.after(0, _do)

    def _set_status(self, msg: str) -> None:
        def _do():
            self.scan_status.configure(text=msg)
        self.after(0, _do)

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
        self.staff_status.configure(
            text=f"Enrolled: {self.profile.name} ({self.profile.staff_id}) | {self.profile.position} | {self.profile.cycle_year}"
        )
        self._log(f"✅ Enrolled / loaded profile: {self.profile.staff_id} ({self.profile.name})")
        _play_sound("vamp.wav")
        self._refresh_expectations_snapshot()

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

        try:
            if import_task_agreement_excel is not None:
                import_task_agreement_excel(self.profile, self.task_agreement_path)
                self._log("✅ Task Agreement imported into contract profile (KPIs updated).")
            else:
                self._log("⚠️ TA importer not available (backend/contracts/task_agreement_import.py).")
        except Exception as e:
            self._log(f"❌ Task Agreement import failed: {e}")
            self._log(traceback.format_exc())

        # Build expectations JSON (used by Ollama prompt + UI snapshot)
        self._rebuild_expectations()
        _play_sound("vamp.wav")
        self._refresh_expectations_snapshot()

    def _generate_initial_pa(self) -> None:
        if not self._ensure_profile():
            return
        try:
            if generate_initial_pa is None:
                raise RuntimeError("backend/contracts/pa_excel.py not available")
            out = generate_initial_pa(self.profile, OFFLINE_RESULTS_DIR)
            self.pa_initial_path = Path(out)
            self._log(f"✅ Initial PA generated at: {self.pa_initial_path}")
        except Exception as e:
            self._log(f"❌ Error generating Initial PA: {e}")
            self._log(traceback.format_exc())
        self._rebuild_expectations()
        _play_sound("vamp.wav")
        self._refresh_expectations_snapshot()

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

    def _rebuild_expectations(self) -> None:
        if not self._ensure_profile():
            return
        if build_staff_expectations is None:
            self._log("⚠️ expectation_engine.build_staff_expectations not available.")
            return
        if not self.task_agreement_path:
            # It's okay: user might have a PA but no TA yet; we still can attempt with None.
            self._log("ℹ️ No Task Agreement selected yet – expectations will be limited.")
        try:
            ta_path = str(self.task_agreement_path) if self.task_agreement_path else ""
            pa_path = str(self.pa_initial_path) if self.pa_initial_path else None
            self.expectations = build_staff_expectations(self.profile.staff_id, ta_path, pa_path)
            self._log("✅ Expectations JSON rebuilt (for contextual scoring).")
        except Exception as e:
            self._log(f"⚠️ Could not rebuild expectations: {e}")

    def _refresh_expectations_snapshot(self) -> None:
        snap = ""
        if self.profile and load_staff_expectations is not None:
            try:
                self.expectations = load_staff_expectations(self.profile.staff_id) or {}
                # Compact friendly snapshot (not full raw)
                snap = json.dumps(self.expectations, ensure_ascii=False, indent=2)[:6000]
            except Exception as e:
                snap = f"(Could not load expectations: {e})"
        elif self.profile:
            snap = "Import Task Agreement / Generate PA to populate expectations."
        else:
            snap = "Import Task Agreement / Generate PA to populate expectations."

        self.expectations_text.config(state="normal")
        self.expectations_text.delete("1.0", "end")
        self.expectations_text.insert("1.0", snap)
        self.expectations_text.config(state="disabled")

    # ---------------------------
    # Folder / scan actions
    # ---------------------------
    def _choose_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select evidence folder")
        if not folder:
            return
        self.current_evidence_folder = Path(folder)
        self.folder_var.set(str(self.current_evidence_folder))
        self._log(f"📁 Selected evidence folder: {self.current_evidence_folder}")

    def _get_kpa_hint_code(self) -> Optional[str]:
        label = (self.kpa_var.get() or "").strip().upper()
        if label in {"KPA1", "KPA2", "KPA3", "KPA4", "KPA5"}:
            return label
        return None

    def _start_scan(self) -> None:
        if not self._ensure_profile():
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

        self._scan_thread = threading.Thread(target=self._scan_worker, daemon=True)
        self._scan_thread.start()

    def _stop_scan(self) -> None:
        self._stop_flag.set()
        self._set_status("Stopping...")
        self._log("🛑 Stop requested. Finishing current item...")

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
            self.after(0, lambda: self.tree.delete(*self.tree.get_children()))
            self._log(f"🔎 Starting scan of {len(artefacts)} artefacts for month {month_bucket}…")

            for path in artefacts:
                if self._stop_flag.is_set():
                    self._log("🛑 Scan stopped by user.")
                    break

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

                self.rows.append(row)
                self.after(0, lambda r=row: self.tree.insert("", "end", values=[r.get(c, "") for c in TABLE_COLUMNS]))

                if impact:
                    self._log(f"{path.name} → {impact}")
                elif row.get("status") == "needs_review":
                    self._log(f"{path.name} → needs review (no impact summary)")
                else:
                    self._log(f"{path.name} → (no impact summary)")

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
            self._log("✅ Scan complete.")
            _play_sound("vamp.wav")

        except Exception as e:
            self._set_status("Idle")
            self._log(f"❌ Fatal scan error: {e}")
            self._log(traceback.format_exc())

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
