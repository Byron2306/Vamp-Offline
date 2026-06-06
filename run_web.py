#!/usr/bin/env python3
"""
VAMP Web Server - Comprehensive API backend with Groq AI integration
"""

import os
import json
import time
import logging
import argparse
import subprocess
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any
from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS
from werkzeug.utils import secure_filename
import requests

# Temporary request logging (for debugging incoming AI prompts)
REQUEST_LOGGING_ENABLED = True
REQUEST_LOGGING_DURATION = 60  # seconds to keep logging after server start
REQUEST_LOGGING_START = time.time()
APP_ROOT = Path(os.getenv("VAMP_APP_ROOT", Path(__file__).resolve().parent)).resolve()
REQUEST_LOG_FILE = Path(os.getenv("VAMP_LOG_DIR", APP_ROOT / "logs")) / "vamp_requests.log"

# Temporary safety switch: when True, prevent automatic KPA/weight dumps
DISABLE_AUTO_KPA = True
# Import VAMP backend modules
try:
    from backend.staff_profile import StaffProfile, create_or_load_profile
    STAFF_PROFILE_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Could not import StaffProfile: {e}")
    STAFF_PROFILE_AVAILABLE = False
    StaffProfile = None
    create_or_load_profile = None

try:
    from backend.expectation_engine import parse_task_agreement, build_expectations_from_ta
    EXPECTATION_ENGINE_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Could not import expectation_engine: {e}")
    parse_task_agreement = None
    build_expectations_from_ta = None

try:
    from task_map import _hid
    TASK_MAP_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Could not import task_map: {e}")
    TASK_MAP_AVAILABLE = False
    _hid = None

try:
    from backend.nwu_brain_scorer import brain_score_evidence
    BRAIN_SCORER_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Could not import brain_score_evidence: {e}")
    BRAIN_SCORER_AVAILABLE = False
    brain_score_evidence = None

try:
    from backend.outlook_evidence_collector import collect_outlook_candidates, describe_search_plan_queries
    OUTLOOK_COLLECTOR_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Could not import collect_outlook_candidates: {e}")
    OUTLOOK_COLLECTOR_AVAILABLE = False
    collect_outlook_candidates = None
    describe_search_plan_queries = None

try:
    from backend.efundi_evidence_collector import collect_efundi_candidates
    EFUNDI_COLLECTOR_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Could not import collect_efundi_candidates: {e}")
    EFUNDI_COLLECTOR_AVAILABLE = False
    collect_efundi_candidates = None

try:
    from backend.work_context import (
        draft_work_context_from_ta,
        ensure_work_context_schema,
        interview_questions,
        load_work_context,
        save_work_context,
    )
    WORK_CONTEXT_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Could not import work_context helpers: {e}")
    WORK_CONTEXT_AVAILABLE = False
    draft_work_context_from_ta = None
    ensure_work_context_schema = None
    interview_questions = None
    load_work_context = None
    save_work_context = None

try:
    from backend.runtime_dependencies import dependency_status, install_playwright_chromium
    RUNTIME_DEPENDENCIES_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Could not import runtime dependency helpers: {e}")
    RUNTIME_DEPENDENCIES_AVAILABLE = False
    dependency_status = None
    install_playwright_chromium = None

print(f"Expectation engine available: {EXPECTATION_ENGINE_AVAILABLE}")

# Flask setup
app = Flask(__name__, static_folder=str(APP_ROOT))
CORS(app)

# Configuration
UPLOAD_FOLDER = Path(os.getenv("VAMP_UPLOAD_DIR", APP_ROOT / "uploads")).expanduser()
DATA_FOLDER = Path(os.getenv("VAMP_DATA_DIR", APP_ROOT / "backend" / "data")).expanduser()
CONTRACTS_FOLDER = DATA_FOLDER / "contracts"
EVIDENCE_FOLDER = DATA_FOLDER / "evidence"
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
DATA_FOLDER.mkdir(parents=True, exist_ok=True)

# LLM Provider Configuration (Groq by default, fallback to Ollama)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq")  # "groq" or "ollama"

# Groq configuration (free cloud API)
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_TIMEOUT = float(os.getenv("GROQ_TIMEOUT", "60"))

# Ollama configuration (local fallback)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "180"))
DEFAULT_PORT = int(os.getenv("PORT", "5050"))
PORT = DEFAULT_PORT

# Global state
profiles = {}
expectations_cache = {}
evidence_store = None
event_clients = []

# Debug flag (set VAMP_DEBUG=true to enable)
DEBUG = os.getenv('VAMP_DEBUG', 'false').lower() == 'true'

# Set up logging
logging.basicConfig(level=logging.DEBUG if DEBUG else logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def dlog(*args, **kwargs):
    if DEBUG:
        logger.debug(' '.join(str(arg) for arg in args))

# Load guidance templates (if any)
try:
    from backend.guidance_renderer import load_templates, render_best_template
    GUIDANCE_TEMPLATES = load_templates(DATA_FOLDER / 'guidance_templates.json')
    dlog(f"Loaded {len(GUIDANCE_TEMPLATES)} guidance templates")
except Exception as _e:
    GUIDANCE_TEMPLATES = []
    dlog(f"Guidance templates not available: {_e}")

# ============================================================
# LLM INTEGRATION (centralized wrapper)
# ============================================================
try:
    from backend.llm.ollama_client import query_ollama as central_query_ollama
    LLM_WRAPPER_AVAILABLE = True
except Exception as _e:
    central_query_ollama = None
    LLM_WRAPPER_AVAILABLE = False


def query_ollama(prompt: str, context: Dict = None) -> str:
    """
    Query the configured LLM via the centralized wrapper in `backend.llm.ollama_client`.
    The wrapper prefers Groq when `GROQ_API_KEY` is set and falls back to Ollama.
    """
    # Preserve mock behavior
    use_mock = os.getenv('USE_MOCK_OLLAMA', '0') in ('1', 'true', 'True')
    if use_mock:
        return run_mock_ollama(prompt, context)

    # Prepend a simple context block if provided so the centralized wrapper sees it
    if context:
        try:
            context_lines = []
            for k, v in (context.items()):
                context_lines.append(f"- {k}: {v}")
            ctx = "\n".join(context_lines)
            prompt = f"Context:\n{ctx}\n\nUser Question: {prompt}"
        except Exception:
            pass

    if LLM_WRAPPER_AVAILABLE and central_query_ollama:
        try:
            return central_query_ollama(prompt)
        except Exception as e:
            print(f"Central LLM wrapper error: {e}")
            try:
                return run_mock_ollama(prompt, context)
            except Exception:
                return "AI service error. Please configure GROQ_API_KEY or ensure Ollama is running."

    return "AI not configured. Please set GROQ_API_KEY or ensure Ollama is running."


def build_vamp_prompt(question: str, context: Dict | None = None) -> str:
    """Build a persona-anchored prompt for VAMP with optional month-review constraints."""
    ctx = context or {}
    name = ctx.get('name') or ctx.get('staff_name') or ctx.get('staff') or "there"
    month = ctx.get('scan_month') or ctx.get('month')
    q_lc = (question or "").lower()

    is_month_review = False
    if month and any(kw in q_lc for kw in ["month review", "monthly review", "review for", "review of"]):
        is_month_review = True

    instructions = [
        "You are VAMP, Byron Bunt's Virtual Academic Management Partner and gothic academic performance assistant.",
        f"Address the user by name in the first sentence (use '{name}').",
        "Identify yourself as VAMP.",
        "Keep the Dracula gothic persona tasteful and professional: sharp, warm, evidence-focused, and never gimmicky.",
        "Keep responses concise and actionable.",
        "When asked about specific tasks, recommendations, or KPAs, provide detailed, specific answers based on NWU policies and the user's context.",
        "For general questions, focus exclusively on NWU academic matters, performance agreements, and related administrative processes.",
        "Do not provide generic or vague responses; always tailor answers to the specific query and user's situation."
    ]

    if is_month_review:
        instructions.extend([
            f"This is a month review for {month}.",
            "Only discuss this month; do not mention other months or the overall year.",
            f"Start with the heading: 'Month Review: {month}'.",
            "Provide specific details about tasks, evidence requirements, and completion status for this month."
        ])

    return "System Instructions:\n" + "\n".join(f"- {line}" for line in instructions) + f"\n\nUser Question: {question}"


def run_mock_ai(prompt: str, context: Dict = None) -> str:
    """
    Generate knowledgeable, system-aware guidance based on VAMP capabilities and NWU context.
    """
    import random
    try:
        ctx = context or {}
        name = ctx.get('name') or ctx.get('staff_name') or ctx.get('staff') or "there"
        month = ctx.get('scan_month') or ctx.get('month')
        current_tab = ctx.get('current_tab') or ''
        # Extract the actual user question from the prompt to avoid matching
        # against system instructions that may mention keywords like 'KPA'.
        prompt_text = (prompt or "").strip()
        user_text = ""
        try:
            user_marker = "user question:"
            idx = prompt_text.lower().find(user_marker)
            if idx != -1:
                user_text = prompt_text[idx + len(user_marker):].strip()
            else:
                # Fallback: take the last paragraph (after the last double newline)
                import re
                parts = re.split(r'\n\s*\n', prompt_text)
                if parts:
                    candidate = parts[-1].strip()
                    # If the candidate is very long (e.g., whole system block), take last 200 chars
                    user_text = candidate if len(candidate) < 500 else candidate[-500:]
                else:
                    user_text = prompt_text
        except Exception:
            user_text = prompt_text

        # Debug: log prompt vs extracted user text to server output and request log file for troubleshooting
        try:
            preview_prompt = prompt_text[:800].replace('\n', '\\n')
            preview_user = user_text[:800].replace('\n', '\\n')
            print(f"[run_mock_ai] prompt_preview={preview_prompt}")
            print(f"[run_mock_ai] user_text_preview={preview_user}")
            # Append to request log if enabled and within duration
            try:
                if REQUEST_LOGGING_ENABLED and (time.time() - REQUEST_LOGGING_START) <= REQUEST_LOGGING_DURATION:
                    REQUEST_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
                    with open(REQUEST_LOG_FILE, 'a') as lf:
                        lf.write(f"{datetime.utcnow().isoformat()}\trun_mock_ai\tuser_text:\t{preview_user}\n")
            except Exception:
                pass
        except Exception:
            pass

        prompt_lc = (user_text or "").lower()
        
        # Personalized greeting
        greeting = f"Hi {name}, VAMP here."

        # Short greeting handler: if the user just said 'hi' or similar, reply briefly
        short_greetings = ["hi", "hello", "hey", "hiya"]
        # If the user text is a single short greeting, respond succinctly
        if prompt_lc.strip() in short_greetings or (len(prompt_lc.split()) <= 2 and any(g in prompt_lc for g in short_greetings)):
            return f"Hi {name}, I'm VAMP. How can I help you today?"
        
        # Evidence log / score questions when on evidence tab
        evidence_summary = ctx.get('evidence_summary')
        if evidence_summary and any(kw in prompt_lc for kw in ["score", "rating", "how am i doing", "my evidence", "my progress", "average", "performance"]):
            avg = float(evidence_summary.get('avg_rating', 0))
            total = evidence_summary.get('total_evidence', 0)
            mapped = evidence_summary.get('mapped_evidence', 0)
            tiers = evidence_summary.get('tier_breakdown', {})
            month_filter = evidence_summary.get('month_filter', 'all')
            
            # Interpret the score based on NWU scale (3 = basic compliance)
            if avg >= 4.0:
                interpretation = "Excellent! You're showing real IMPACT beyond basic compliance."
            elif avg >= 3.0:
                interpretation = "You're at BASIC compliance level - doing your job. To score higher, show measurable IMPACT."
            elif avg >= 2.0:
                interpretation = "Below target. You need more evidence showing you're meeting expectations."
            else:
                interpretation = "Needs attention. Upload more evidence demonstrating your work."
            
            tier_text = ', '.join([f"{t}: {c}" for t, c in tiers.items()]) if tiers else 'None yet'
            scope = f"for {month_filter}" if month_filter != 'all' else "across all months"
            
            return f"{greeting} Looking at your evidence {scope}: You have {total} files uploaded, {mapped} mapped to tasks. Your average rating is {avg}/5.0. {interpretation} Tier breakdown: {tier_text}. Remember: 3.0 = basic compliance (doing your job), 4.0+ = exceeding expectations (showing impact), 5.0 = exceptional (transformational work)."
        
        # Task-specific guidance (check this first so 'task' keyword doesn't trigger month summary)
        task = ctx.get('task') or {}
        title = task.get('title') or task.get('task') or ''
        kpa = task.get('kpa') or task.get('kpa_code') or ''
        hints = task.get('evidence_hints') or []
        evidence_required = task.get('evidence_required') or ''
        min_req = task.get('minimum_count') or task.get('min_required') or 1

        if title and any(kw in prompt_lc for kw in ["how do i", "help", "recommend", "what should i", "evidence", "complete this task", "this task"]):
            response = f"{greeting} For '{title[:60]}{'...' if len(title) > 60 else ''}':"
            if kpa:
                response += f" This falls under {kpa}."
            if min_req:
                response += f" You need at least {min_req} evidence item(s)."
            if evidence_required:
                response += f" Suggested evidence: {evidence_required[:200]}{'...' if len(evidence_required) > 200 else ''}."
            elif hints:
                response += f" Good evidence types: {', '.join(hints[:5])}."
            response += " If you want, I can suggest exact filenames or phrasing for your evidence uploads."
            return response

        # Month tasks context when on expectations tab
        month_tasks = ctx.get('month_tasks')
        # Only show month summary when no specific task is present in context
        if not task and month_tasks and any(kw in prompt_lc for kw in ["this month", "monthly", "what do i need", "expectations", "required", "month review"]):
            task_month = month_tasks.get('month', month)
            total = month_tasks.get('total_tasks', 0)
            by_kpa = month_tasks.get('by_kpa', {})
            samples = month_tasks.get('sample_tasks', [])

            kpa_breakdown = ', '.join([f"{k}: {v}" for k, v in by_kpa.items()]) if by_kpa else 'None'
            sample_titles = [s.get('title', '')[:50] for s in samples[:3]]

            return f"{greeting} For {task_month}, you have {total} tasks to complete. Breakdown by KPA: {kpa_breakdown}. Some key tasks: {'; '.join(sample_titles) if sample_titles else 'None yet'}. Upload evidence for each task, then check month status to see what's still needed."
        
        # VAMP system knowledge responses
        if any(kw in prompt_lc for kw in ["what can you do", "what are you", "who are you", "your capabilities", "help me", "how do you work"]):
            return f"{greeting} I'm VAMP, your Virtual Academic Management Partner for academic performance evidence at North-West University. I help you track your Performance Agreement by: 1) Importing your Task Agreement Excel to generate monthly expectations across all 5 KPAs, 2) Scanning and classifying evidence files using NWU Brain scoring, 3) Mapping evidence to specific tasks, 4) Tracking completion per month, and 5) Generating your final PA report with weights and percentages. Upload your TA, then scan evidence files for each month."
        
        # KPA info: disabled when DISABLE_AUTO_KPA is True; otherwise require explicit question intent
        if not DISABLE_AUTO_KPA and any(kw in prompt_lc for kw in ["kpa", "key performance", "performance area"]) and any(qw in prompt_lc for qw in ["what", "explain", "describe", "list", "tell me"]):
            return f"{greeting} NWU uses 5 Key Performance Areas: KPA1 - Teaching & Learning (includes supervision, eFundi, assessments, curriculum development), KPA2 - Occupational Health & Safety (compliance requirements, risk assessments), KPA3 - Research & Innovation (publications, grants, postgraduate supervision, conferences), KPA4 - Academic Leadership & Administration (committees, coordination, quality assurance), KPA5 - Social Responsiveness (community engagement, industry partnerships, professional development). Your specific weights and hours come from your Task Agreement - check the Expectations tab for your personalized breakdown."
        
        if any(kw in prompt_lc for kw in ["evidence", "upload", "scan", "document"]):
            return f"{greeting} To add evidence: 1) Go to Expectations tab, 2) Click 'Scan Evidence', 3) Select your files (PDFs, DOCs, images, etc.), 4) Set the month bucket, 5) Click Upload & Scan. I'll use NWU Brain to classify them by KPA and map them to your tasks. For best results, lock evidence directly to specific tasks using the task's scan button."
        
        if any(kw in prompt_lc for kw in ["efundi", "lms", "blackboard"]):
            return f"{greeting} For eFundi/LMS evidence, export screenshots showing: your course site setup, uploaded resources, gradebook entries, or student submissions. These map well to KPA1 Teaching & Learning tasks. The system recognizes eFundi-related keywords automatically."
        
        if any(kw in prompt_lc for kw in ["report", "generate", "pa report", "performance agreement", "final"]):
            return f"{greeting} To generate your PA Report: 1) Ensure all months have evidence uploaded, 2) Lock completed months, 3) Go to Reports tab, 4) Click Generate Report. The output includes all 5 KPAs with your actual weights (%), hours, outputs from your TA, and completion status. You can export to Excel."
        
        if not DISABLE_AUTO_KPA and any(kw in prompt_lc for kw in ["weight", "percentage", "hours", "%"]):
            return f"{greeting} Your KPA weights and hours come directly from your Task Agreement import. For example, Teaching might be 47% / 793 hours, Research 36% / 525 hours, etc. These are calculated from your contracted teaching load, supervision, research outputs, and other commitments. Check the Expectations tab for your specific breakdown."
        
        if any(kw in prompt_lc for kw in ["lock", "complete", "finish", "month done"]):
            return f"{greeting} To lock a month: 1) Check Month Status to verify all tasks are covered, 2) For tasks with no supporting documents, click 'No Evidence' to mark them, 3) Once all tasks show green or gold, the Lock button enables. Locked months contribute to your mid-year and end-year reviews."
        
        # Scoring explanation
        if any(kw in prompt_lc for kw in ["score", "rating", "scale", "what does", "mean"]):
            return f"{greeting} NWU scoring works like this: 1-2 = Not meeting expectations (below compliance). 3 = BASIC COMPLIANCE - you're doing your job, meeting minimum requirements. 4 = EXCEEDING - you're showing measurable IMPACT beyond the basics. 5 = EXCEPTIONAL - transformational work with sector-wide or institutional influence. To score above 3, your evidence needs to show outcomes, impact, and how you went beyond just completing tasks."
        
        # Month review responses - require explicit month/status intent
        if not DISABLE_AUTO_KPA and month and any(kw in prompt_lc for kw in ["month review", "monthly review", "review for", "review of", "status", "progress"]) and any(qw in prompt_lc for qw in ["check", "status", "how many", "progress", "review", "what"]):
            return f"{greeting} For {month}, check the Expectations tab and click 'Check Month Status'. This shows each task's evidence count vs minimum required. Upload more evidence for incomplete tasks, or mark them 'No Evidence' if you genuinely have none. Once all tasks are accounted for, lock the month."
        
        # Task-specific guidance
        task = ctx.get('task') or {}
        title = task.get('title') or task.get('task') or ''
        kpa = task.get('kpa') or task.get('kpa_code') or ''
        hints = task.get('evidence_hints') or []
        evidence_required = task.get('evidence_required') or ''
        min_req = task.get('minimum_count') or task.get('min_required') or 1
        
        if title:
            response = f"{greeting} For '{title[:60]}{'...' if len(title) > 60 else ''}':"
            if kpa:
                response += f" This is under {kpa}."
            if min_req:
                response += f" You need at least {min_req} evidence item(s)."
            if evidence_required:
                response += f" Look for: {evidence_required[:150]}{'...' if len(evidence_required) > 150 else ''}"
            elif hints:
                response += f" Good evidence types: {', '.join(hints[:5])}."
            return response
        
        # Context-aware generic response
        if current_tab == 'evidence':
            return f"{greeting} You're viewing the Evidence Log. Ask me about your scores, what the ratings mean, or how to improve your evidence quality. Remember: 3 = basic compliance, 4+ = showing impact!"
        elif current_tab == 'expectations':
            return f"{greeting} You're on Expectations. Ask me about your tasks for {month or 'the selected month'}, what evidence you need, or how to check your month status."
        
        # Generic helpful response
        return f"{greeting} I'm here to help with your NWU Performance Agreement. You can ask me about: your scores and ratings, KPAs and their weights, tasks for this month, how to upload evidence, or generating your PA report. What would you like to know?"
        
    except Exception as e:
        print(f"Mock AI error: {e}")
        return "I'm having a moment - please try your question again."

# Alias for backward compatibility
run_mock_ollama = run_mock_ai

# ============================================================
# STATIC FILES
# ============================================================

@app.route('/')
def serve_index():
    response = send_from_directory('.', 'index.html')
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/<path:path>')
def serve_static(path):
    response = send_from_directory('.', path)
    # Prevent caching for JS and HTML files
    if path.endswith(('.js', '.html')):
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response

# ============================================================
# PROFILE ENROLMENT
# ============================================================

@app.route('/api/profile/enrol', methods=['POST'])
def enrol_profile():
    """
    Enrol or load a staff profile
    """
    try:
        data = request.json
        staff_id = data.get('staff_id')
        cycle_year = data.get('cycle_year')
        
        if not staff_id or not cycle_year:
            return jsonify({"error": "Missing staff_id or cycle_year"}), 400
        
        # Create or load profile
        if STAFF_PROFILE_AVAILABLE:
            try:
                name = data.get('name') or 'Unknown'
                position = data.get('position') or 'Academic'
                faculty = data.get('faculty') or ''
                school = data.get('school') or ''
                subject_group = data.get('subject_group') or ''
                research_entity = data.get('research_entity') or ''
                campus = data.get('campus') or ''
                director = data.get('director') or ''
                subject_group_leader = data.get('subject_group_leader') or ''
                executive_dean = data.get('executive_dean') or ''
                research_dean = data.get('research_dean') or ''
                school_admin = data.get('school_admin') or ''
                modules_context = data.get('modules_context') or ''
                manager = data.get('manager') or ''

                # Prefer helper that also loads existing contract JSON
                if create_or_load_profile is not None:
                    profile = create_or_load_profile(
                        staff_id=staff_id,
                        name=name,
                        position=position,
                        cycle_year=int(cycle_year),
                        faculty=faculty,
                        school=school,
                        subject_group=subject_group,
                        research_entity=research_entity,
                        campus=campus,
                        director=director,
                        subject_group_leader=subject_group_leader,
                        executive_dean=executive_dean,
                        research_dean=research_dean,
                        school_admin=school_admin,
                        modules_context=modules_context,
                        line_manager=manager,
                    )
                else:
                    profile = StaffProfile(
                        staff_id=staff_id,
                        name=name,
                        position=position,
                        cycle_year=int(cycle_year),
                        faculty=faculty,
                        school=school,
                        subject_group=subject_group,
                        research_entity=research_entity,
                        campus=campus,
                        director=director,
                        subject_group_leader=subject_group_leader,
                        executive_dean=executive_dean,
                        research_dean=research_dean,
                        school_admin=school_admin,
                        modules_context=modules_context,
                        line_manager=manager,
                        kpas=[],
                    )
            except Exception as e:
                print(f"StaffProfile creation error: {e}. Using mock profile.")
                profile = {
                    "staff_id": staff_id,
                    "cycle_year": int(cycle_year),
                    "name": data.get('name', 'Unknown'),
                    "position": data.get('position', 'Academic'),
                    "faculty": data.get('faculty', 'Unknown'),
                    "school": data.get('school', ''),
                    "subject_group": data.get('subject_group', ''),
                    "research_entity": data.get('research_entity', ''),
                    "campus": data.get('campus', ''),
                    "director": data.get('director', ''),
                    "subject_group_leader": data.get('subject_group_leader', ''),
                    "executive_dean": data.get('executive_dean', ''),
                    "research_dean": data.get('research_dean', ''),
                    "school_admin": data.get('school_admin', ''),
                    "modules_context": data.get('modules_context', ''),
                    "manager": data.get('manager', 'Unknown')
                }
        else:
            # Mock profile
            profile = {
                "staff_id": staff_id,
                "cycle_year": int(cycle_year),
                "name": data.get('name', 'Unknown'),
                "position": data.get('position', 'Academic'),
                "faculty": data.get('faculty', 'Unknown'),
                "school": data.get('school', ''),
                "subject_group": data.get('subject_group', ''),
                "research_entity": data.get('research_entity', ''),
                "campus": data.get('campus', ''),
                "director": data.get('director', ''),
                "subject_group_leader": data.get('subject_group_leader', ''),
                "executive_dean": data.get('executive_dean', ''),
                "research_dean": data.get('research_dean', ''),
                "school_admin": data.get('school_admin', ''),
                "modules_context": data.get('modules_context', ''),
                "manager": data.get('manager', 'Unknown')
            }
        
        profile_key = f"{staff_id}_{cycle_year}"
        profiles[profile_key] = profile
        
        return jsonify({
            "status": "success",
            "profile": {
                "staff_id": staff_id,
                "cycle_year": cycle_year,
                "name": data.get('name')
            }
        })
    
    except Exception as e:
        print(f"Enrolment error: {e}")
        return jsonify({"error": str(e)}), 500

# ============================================================
# TASK AGREEMENT IMPORT
# ============================================================

@app.route('/api/ta/import', methods=['POST'])
def import_task_agreement():
    """
    Import Task Agreement from uploaded Excel file OR use existing contract
    """
    try:
        staff_id = request.form.get('staff_id')
        cycle_year = request.form.get('cycle_year')
        
        if not staff_id or not cycle_year:
            return jsonify({"error": "Missing staff_id or cycle_year"}), 400
        
        # Prefer uploaded file when provided. If no uploaded file, fall back to existing contract.
        contract_file = CONTRACTS_FOLDER / f"contract_{staff_id}_{cycle_year}.json"

        uploaded_file = request.files.get('file') if 'file' in request.files else None

        if uploaded_file and getattr(uploaded_file, 'filename', None):
            # Process uploaded TA (overrides any existing contract)
            filename = secure_filename(uploaded_file.filename)
            filepath = UPLOAD_FOLDER / filename
            uploaded_file.save(str(filepath))

            if EXPECTATION_ENGINE_AVAILABLE and parse_task_agreement and build_expectations_from_ta:
                try:
                    ta_summary = parse_task_agreement(str(filepath))
                    expectations = build_expectations_from_ta(staff_id, int(cycle_year), ta_summary)

                    # Save expectations (backup existing file first)
                    expectations_file = CONTRACTS_FOLDER.parent / "staff_expectations" / f"expectations_{staff_id}_{cycle_year}.json"
                    expectations_file.parent.mkdir(parents=True, exist_ok=True)
                    if expectations_file.exists():
                        try:
                            bak = expectations_file.with_suffix('.json.bak')
                            bak_name = expectations_file.with_name(f"{expectations_file.stem}.{int(time.time())}.bak")
                            expectations_file.rename(bak_name)
                        except Exception:
                            pass

                    with open(expectations_file, 'w') as f:
                        json.dump(expectations, f, indent=2)

                    # Also save TA summary
                    ta_file = CONTRACTS_FOLDER / f"ta_summary_{staff_id}_{cycle_year}.json"
                    ta_file.parent.mkdir(parents=True, exist_ok=True)
                    with open(ta_file, 'w') as f:
                        json.dump(ta_summary, f, indent=2)

                    # Immediately ensure tasks are present in the progress DB
                    try:
                        from progress_store import ProgressStore
                        from mapper import ensure_tasks
                        store = ProgressStore()
                        ensure_tasks(store, staff_id=staff_id, year=int(cycle_year), expectations=expectations)
                    except Exception as e:
                        print(f"Warning: could not upsert tasks after import: {e}")

                    work_context, context_questions = _ensure_work_context_draft(staff_id, int(cycle_year), ta_summary)

                    return jsonify({
                        "status": "success",
                        "tasks_count": len(expectations.get('tasks', [])),
                        "kpas_count": len(expectations.get('kpa_summary', {})),
                        "expectations_path": str(expectations_file),
                        "work_context": work_context,
                        "context_questions": context_questions,
                        "message": "Uploaded TA parsed and persisted; existing contract (if any) was ignored."
                    })
                except Exception as parse_error:
                    print(f"TA parsing failed: {parse_error}")
                    import traceback
                    traceback.print_exc()
            else:
                print("TA parser not available.")
                return jsonify({"error": "Task Agreement parser not available. Please ensure the expectation engine is installed and import a TA."}), 500

        # If no uploaded file, try using existing contract (if present)
        if contract_file.exists():
            # Use existing contract
            with open(contract_file, 'r') as f:
                ta_summary = json.load(f)
            
            if EXPECTATION_ENGINE_AVAILABLE and build_expectations_from_ta:
                expectations = build_expectations_from_ta(staff_id, int(cycle_year), ta_summary)

                # Save expectations (backup existing file first)
                expectations_file = CONTRACTS_FOLDER.parent / "staff_expectations" / f"expectations_{staff_id}_{cycle_year}.json"
                expectations_file.parent.mkdir(parents=True, exist_ok=True)
                if expectations_file.exists():
                    try:
                        bak_name = expectations_file.with_name(f"{expectations_file.stem}.{int(time.time())}.bak")
                        expectations_file.rename(bak_name)
                    except Exception:
                        pass

                with open(expectations_file, 'w') as f:
                    json.dump(expectations, f, indent=2)

                # Immediately ensure tasks are present in the progress DB
                try:
                    from progress_store import ProgressStore
                    from mapper import ensure_tasks
                    store = ProgressStore()
                    ensure_tasks(store, staff_id=staff_id, year=int(cycle_year), expectations=expectations)
                except Exception as e:
                    print(f"Warning: could not upsert tasks after import: {e}")

                work_context, context_questions = _ensure_work_context_draft(staff_id, int(cycle_year), ta_summary)

                return jsonify({
                    "status": "success",
                    "tasks_count": len(expectations.get('tasks', [])),
                    "kpas_count": len(expectations.get('kpa_summary', {})),
                    "work_context": work_context,
                    "context_questions": context_questions,
                    "message": f"Generated {len(expectations.get('tasks', []))} tasks from existing contract"
                })
        
        # If no contract, parse from uploaded file
        if 'file' not in request.files:
            return jsonify({"error": "No file uploaded and no existing contract found. Please upload a Task Agreement."}), 400
        
        file = request.files['file']
        
        # Save file
        filename = secure_filename(file.filename)
        filepath = UPLOAD_FOLDER / filename
        file.save(str(filepath))
        
        # Parse Task Agreement and build expectations
        if EXPECTATION_ENGINE_AVAILABLE and parse_task_agreement and build_expectations_from_ta:
            try:
                # Parse the TA
                ta_summary = parse_task_agreement(str(filepath))
                
                # Build expectations from TA
                expectations = build_expectations_from_ta(staff_id, int(cycle_year), ta_summary)
                
                # Save expectations
                expectations_file = CONTRACTS_FOLDER.parent / "staff_expectations" / f"expectations_{staff_id}_{cycle_year}.json"
                expectations_file.parent.mkdir(parents=True, exist_ok=True)

                with open(expectations_file, 'w') as f:
                    json.dump(expectations, f, indent=2)

                # Also save TA summary
                ta_file = CONTRACTS_FOLDER / f"ta_summary_{staff_id}_{cycle_year}.json"
                ta_file.parent.mkdir(parents=True, exist_ok=True)

                with open(ta_file, 'w') as f:
                    json.dump(ta_summary, f, indent=2)

                # Immediately ensure tasks are present in the progress DB
                try:
                    from progress_store import ProgressStore
                    from mapper import ensure_tasks
                    store = ProgressStore()
                    ensure_tasks(store, staff_id=staff_id, year=int(cycle_year), expectations=expectations)
                except Exception as e:
                    print(f"Warning: could not upsert tasks after import: {e}")

                work_context, context_questions = _ensure_work_context_draft(staff_id, int(cycle_year), ta_summary)

                return jsonify({
                    "status": "success",
                    "tasks_count": len(expectations.get('tasks', [])),
                    "kpas_count": len(expectations.get('kpa_summary', {})),
                    "expectations_path": str(expectations_file),
                    "work_context": work_context,
                    "context_questions": context_questions,
                })
            except Exception as parse_error:
                print(f"TA parsing failed: {parse_error}")
                import traceback
                traceback.print_exc()
        else:
            print("TA parser not available.")
            return jsonify({"error": "Task Agreement parser not available. Please ensure the expectation engine is installed and import a TA."}), 500
    
    except Exception as e:
        print(f"TA import error: {e}")
        return jsonify({"error": str(e)}), 500

# ============================================================
# EXPECTATIONS & PROGRESS
# ============================================================

def _load_ta_summary_for_context(staff_id: str, year: int) -> dict:
    ta_file = CONTRACTS_FOLDER / f"ta_summary_{staff_id}_{year}.json"
    contract_file = CONTRACTS_FOLDER / f"contract_{staff_id}_{year}.json"
    for path in (ta_file, contract_file):
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
    return {}


def _ensure_work_context_draft(staff_id: str, year: int, ta_summary: dict) -> tuple[dict, list]:
    if not WORK_CONTEXT_AVAILABLE or load_work_context is None or draft_work_context_from_ta is None or save_work_context is None:
        return {}, []
    existing = load_work_context(staff_id, year) or {}
    context = existing or save_work_context(staff_id, year, draft_work_context_from_ta(staff_id, year, ta_summary or {}))
    if ensure_work_context_schema is not None:
        context = ensure_work_context_schema(context, ta_summary or {})
    questions = interview_questions(context) if interview_questions else []
    return context, questions


@app.route('/api/work-context', methods=['GET'])
def get_work_context():
    try:
        if not WORK_CONTEXT_AVAILABLE or load_work_context is None:
            return jsonify({"error": "Work context helpers unavailable"}), 500
        staff_id = request.args.get('staff_id')
        year = int(request.args.get('year') or datetime.now().year)
        if not staff_id:
            return jsonify({"error": "Missing staff_id"}), 400
        context = load_work_context(staff_id, year) or {}
        if ensure_work_context_schema is not None:
            context = ensure_work_context_schema(context, _load_ta_summary_for_context(staff_id, year))
        return jsonify({"work_context": context, "exists": bool(context)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/work-context/draft', methods=['POST'])
def draft_work_context():
    try:
        if not WORK_CONTEXT_AVAILABLE or draft_work_context_from_ta is None or save_work_context is None:
            return jsonify({"error": "Work context helpers unavailable"}), 500
        data = request.json or {}
        staff_id = str(data.get('staff_id') or '').strip()
        year = int(data.get('year') or datetime.now().year)
        overwrite = bool(data.get('overwrite', False))
        if not staff_id:
            return jsonify({"error": "Missing staff_id"}), 400
        existing = load_work_context(staff_id, year) if load_work_context else {}
        if existing and not overwrite:
            context = existing
        else:
            ta_summary = data.get('ta_summary') if isinstance(data.get('ta_summary'), dict) else _load_ta_summary_for_context(staff_id, year)
            context = draft_work_context_from_ta(staff_id, year, ta_summary or {})
            context = save_work_context(staff_id, year, context)
        if ensure_work_context_schema is not None:
            context = ensure_work_context_schema(context, _load_ta_summary_for_context(staff_id, year))
        questions = interview_questions(context) if interview_questions else []
        return jsonify({"work_context": context, "questions": questions, "question_count": len(questions)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/work-context/questions', methods=['GET'])
def get_work_context_questions():
    try:
        if not WORK_CONTEXT_AVAILABLE or load_work_context is None or interview_questions is None:
            return jsonify({"error": "Work context helpers unavailable"}), 500
        staff_id = request.args.get('staff_id')
        year = int(request.args.get('year') or datetime.now().year)
        if not staff_id:
            return jsonify({"error": "Missing staff_id"}), 400
        ta_summary = _load_ta_summary_for_context(staff_id, year)
        context = load_work_context(staff_id, year) or {}
        if not context and draft_work_context_from_ta is not None:
            context = draft_work_context_from_ta(staff_id, year, ta_summary)
        if ensure_work_context_schema is not None:
            context = ensure_work_context_schema(context, ta_summary)
        questions = interview_questions(context)
        return jsonify({"questions": questions, "question_count": len(questions), "work_context": context})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/work-context', methods=['POST'])
def update_work_context():
    try:
        if not WORK_CONTEXT_AVAILABLE or save_work_context is None:
            return jsonify({"error": "Work context helpers unavailable"}), 500
        data = request.json or {}
        staff_id = str(data.get('staff_id') or '').strip()
        year = int(data.get('year') or datetime.now().year)
        context = data.get('work_context') if isinstance(data.get('work_context'), dict) else data.get('context')
        if not staff_id or not isinstance(context, dict):
            return jsonify({"error": "Missing staff_id or work_context"}), 400
        if ensure_work_context_schema is not None:
            context = ensure_work_context_schema(context, _load_ta_summary_for_context(staff_id, year))
        saved = save_work_context(staff_id, year, context)
        questions = interview_questions(saved) if interview_questions else []
        return jsonify({"status": "success", "work_context": saved, "questions": questions, "question_count": len(questions)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/dependencies/status', methods=['GET'])
def get_dependency_status():
    try:
        if not RUNTIME_DEPENDENCIES_AVAILABLE or dependency_status is None:
            return jsonify({"error": "Runtime dependency helpers unavailable"}), 500
        return jsonify({"success": True, "dependencies": dependency_status()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/dependencies/install-playwright', methods=['POST'])
def install_playwright_dependency():
    try:
        if not RUNTIME_DEPENDENCIES_AVAILABLE or install_playwright_chromium is None:
            return jsonify({"error": "Runtime dependency helpers unavailable"}), 500
        result = install_playwright_chromium()
        status_code = 200 if result.get("ok") else 500
        return jsonify({"success": bool(result.get("ok")), "result": result}), status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _brain_feedback_fields(meta):
    """Return normalized qualitative NWU brain feedback fields from evidence meta."""
    brain = meta.get("brain") if isinstance(meta, dict) else {}
    if not isinstance(brain, dict):
        brain = {}
    return {
        "assessment_summary": brain.get("assessment_summary") or meta.get("assessment_summary") or "",
        "evidence_strengths": brain.get("evidence_strengths") or meta.get("evidence_strengths") or [],
        "review_flags": brain.get("review_flags") or meta.get("review_flags") or [],
        "recommended_actions": brain.get("recommended_actions") or meta.get("recommended_actions") or [],
        "route_confidence": brain.get("route_confidence", meta.get("route_confidence")),
    }

_OUTLOOK_GENERIC_MATCH_TERMS = {
    "and", "the", "for", "with", "from", "this", "that", "task", "agreement",
    "performance", "research", "project", "progress", "work", "academic",
    "faculty", "education", "school", "dear", "regards", "prof", "bunt",
}

def _selected_outlook_task_ids(candidate: dict, requested_task_ids: list[str] | None = None) -> list[str]:
    """Choose conservative task assertions from an Outlook evidence candidate.

    Broad Outlook searches should not let one email satisfy several expectation
    tasks merely because the module code or generic words overlap. A task-click
    search may assert exactly that requested task; month-wide collection only
    asserts the single best non-generic match.
    """
    requested = [str(tid) for tid in (requested_task_ids or []) if str(tid)]
    raw_ids = [str(tid) for tid in (candidate.get("task_candidates") or []) if str(tid)]
    matched = candidate.get("matched_tasks") or []
    source = str(candidate.get("source") or "").lower()
    is_direct_lms = source.startswith("efundi")

    if len(requested) == 1 and requested[0] in raw_ids:
        return [requested[0]]

    usable: list[dict] = []
    for item in matched:
        if not isinstance(item, dict):
            continue
        task_id = str(item.get("task_id") or "")
        if not task_id:
            continue
        if requested and task_id not in requested:
            continue
        terms = [str(t).lower() for t in (item.get("matched_terms") or []) if str(t).strip()]
        if terms and all(t in _OUTLOOK_GENERIC_MATCH_TERMS for t in terms):
            continue

        quality = item.get("match_quality") or {}
        strong_signals = []
        if isinstance(quality, dict):
            for key in ("module_hits", "evidence_hits", "attachment_hits", "phrase_hits"):
                strong_signals.extend(quality.get(key) or [])

        score = float(item.get("score") or 0.0)
        if not strong_signals and score < 4.0:
            continue
        usable.append(item)

    if usable:
        usable.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
        return [str(usable[0].get("task_id"))]

    if is_direct_lms and len(raw_ids) == 1:
        return raw_ids
    return []


def _profile_context_terms(staff_id: str, year: int) -> list[str]:
    """Return enrolment context terms that can safely enrich evidence searches."""
    safe_id = str(staff_id).replace("/", "-").replace("\\", "-")
    path = CONTRACTS_FOLDER / f"contract_{safe_id}_{int(year)}.json"
    if not path.exists():
        return []
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    fields = [
        "faculty",
        "school",
        "subject_group",
        "research_entity",
        "campus",
        "director",
        "subject_group_leader",
        "executive_dean",
        "research_dean",
        "school_admin",
        "modules_context",
        "line_manager",
        "manager",
    ]
    terms: list[str] = []
    seen: set[str] = set()
    for field in fields:
        value = str(profile.get(field) or "").strip()
        if not value:
            continue
        chunks = [value]
        if field in {"modules_context", "school_admin", "director", "subject_group_leader", "executive_dean", "research_dean"}:
            chunks.extend(part.strip() for part in re.split(r"[,;/|]+", value) if part.strip())
        for chunk in chunks:
            marker = chunk.lower()
            if len(chunk) < 3 or marker in seen:
                continue
            seen.add(marker)
            terms.append(chunk)
    return terms

@app.route('/api/progress', methods=['GET'])
def get_progress():
    """
    Get task completion progress for staff/year/month
    """
    try:
        staff_id = request.args.get('staff_id')
        year = request.args.get('year')
        month = request.args.get('month')  # Optional, e.g., "2025-01"
        
        if not staff_id or not year:
            return jsonify({"error": "Missing staff_id or year"}), 400
        
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent))
        from progress_store import ProgressStore
        from mapper import ensure_tasks
        
        store = ProgressStore()
        
        # Ensure tasks exist
        expectations_file = CONTRACTS_FOLDER.parent / "staff_expectations" / f"expectations_{staff_id}_{year}.json"
        if expectations_file.exists():
            with open(expectations_file, 'r') as f:
                expectations = json.load(f)
            ensure_tasks(store, staff_id=staff_id, year=int(year), expectations=expectations)
        
        # Determine month window
        months: List[int]
        if month:
            months = [int(month.split('-')[1])]
        else:
            months = list(range(1, 13))

        # Compute window progress (ProgressStore returns ints, not lists)
        progress: Dict[str, Any] = {}
        months_progress: Dict[str, Any] = {}
        
        try:
            # Aggregate progress for the requested window (all months or a single month)
            progress = store.compute_window_progress(staff_id, int(year), months)
        except Exception as e:
            print(f"Window progress error: {e}")
            progress = {
                "staff_id": staff_id,
                "year": int(year),
                "months": months,
                "expected_tasks": 0,
                "completed_tasks": 0,
                "missing_tasks": [],
                "by_kpa": {},
            }

        # If no specific month requested, build per-month progress map so the UI can fetch once
        try:
            if not month:
                for m in months:
                    try:
                        p = store.compute_window_progress(staff_id, int(year), [m])
                        evidence_rows_m = store.list_evidence(staff_id, int(year), month_bucket=f"{int(year):04d}-{m:02d}")
                        months_progress[f"{int(year):04d}-{m:02d}"] = {
                            "progress": {
                                "total_tasks": int(p.get("expected_tasks", 0)),
                                "completed_count": int(p.get("completed_tasks", 0)),
                                "missing_tasks": p.get("missing_tasks", []),
                                "by_kpa": p.get("by_kpa", {}),
                            },
                            "stats": {
                                "total_tasks": int(p.get("expected_tasks", 0)),
                                "completed_tasks": int(p.get("completed_tasks", 0)),
                                "evidence_count": len(evidence_rows_m)
                            }
                        }
                    except Exception:
                        months_progress[f"{int(year):04d}-{m:02d}"] = {
                            "progress": {"total_tasks": 0, "completed_count": 0, "missing_tasks": [], "by_kpa": {}},
                            "stats": {"total_tasks": 0, "completed_tasks": 0, "evidence_count": 0}
                        }
        except Exception as e:
            print(f"Error building months_progress: {e}")
        
        # Derive completion map (expected - missing) for the window
        task_rows = store.list_tasks_for_window(int(year), months)
        expected_task_ids = [r["task_id"] for r in task_rows]
        missing_ids = {t.get("task_id") for t in (progress.get("missing_tasks") or []) if isinstance(t, dict)}
        completed_ids = set([tid for tid in expected_task_ids if tid not in missing_ids])
        
        # Map hashed task IDs back to original task IDs for frontend compatibility
        task_completion = {}
        expectations_file = CONTRACTS_FOLDER.parent / "staff_expectations" / f"expectations_{staff_id}_{year}.json"
        if expectations_file.exists() and TASK_MAP_AVAILABLE:
            try:
                with open(expectations_file, 'r') as f:
                    expectations_data = json.load(f)
                
                # Create mapping from hashed ID back to original ID (support 'id' or 'task_id')
                # We will expose ONLY the hashed DB task IDs so the frontend uses canonical IDs.
                for task in expectations_data.get('tasks', []):
                    original_id = task.get('id') or task.get('task_id')
                    months_list = task.get('months') or task.get('month') or []
                    if isinstance(months_list, (int, str)):
                        months_list = [months_list]
                    if original_id and months_list:
                        for m in months_list:
                            try:
                                month_int = int(m)
                                hashed_id = _hid(staff_id, str(year), str(original_id), f"{month_int:02d}")
                                if hashed_id in completed_ids:
                                    # Expose only hashed IDs (canonical DB ids)
                                    task_completion[hashed_id] = True
                            except (ValueError, TypeError):
                                continue
            except Exception as e:
                print(f"Error mapping task IDs: {e}")
                # Fallback to hashed IDs
                task_completion = {tid: True for tid in completed_ids}
        else:
            # Fallback to hashed IDs if expectations not available
            task_completion = {tid: True for tid in completed_ids}

        # Ensure only canonical DB task_ids are exposed to the frontend.
        # Some legacy code paths used original expectation IDs; filter those out
        # so the UI only receives hashed (DB) task identifiers.
        try:
            allowed_ids = set(expected_task_ids) | set(completed_ids)
            # Keep only keys that are known canonical IDs
            task_completion = {k: v for k, v in task_completion.items() if k in allowed_ids}
            # Ensure any completed canonical IDs are present
            for tid in completed_ids:
                if tid not in task_completion:
                    task_completion[tid] = True
        except Exception:
            # If anything goes wrong, fall back to the existing mapping
            task_completion = {tid: True for tid in completed_ids}

        # Evidence list for Evidence Log (include top mapped task)
        include_unmapped = str(request.args.get('include_unmapped') or '').lower() in ('1', 'true', 'yes')
        evidence_rows = store.list_evidence(staff_id, int(year), month_bucket=month if month else None)
        evidence_list = []
        hidden_unmapped_count = 0
        seen_evidence_keys = set()
        for ev in evidence_rows:
            evd = dict(ev)
            meta = {}
            try:
                meta = json.loads(evd.get("meta_json") or "{}")
            except Exception:
                meta = {}

            top_task_title = None
            top_task_id = None
            top_conf = None
            mapped_tasks = []
            try:
                mappings = store.list_mappings_for_evidence(evd["evidence_id"])
                if mappings:
                    for m in mappings:
                        try:
                            # sqlite3.Row behaves like a sequence/dict but does not implement `.get()`
                            # access keys safely using Row.keys() and index access
                            row_keys = set(m.keys()) if hasattr(m, 'keys') else set()
                            title = m["title"] if ("title" in row_keys and m["title"]) else m["task_id"]
                            confidence = float(m["confidence"]) if ("confidence" in row_keys and m["confidence"] is not None) else 0.0
                            mapped_tasks.append({
                                "task_id": m["task_id"],
                                "title": title,
                                "confidence": confidence,
                                "mapped_by": m["mapped_by"] if "mapped_by" in row_keys else "",
                                "kpa_code": m["kpa_code"] if "kpa_code" in row_keys else ""
                            })
                        except Exception:
                            continue
                    # First mapping is the top match
                    if mapped_tasks:
                        top_task_id = mapped_tasks[0]["task_id"]
                        top_task_title = mapped_tasks[0]["title"]
                        top_conf = mapped_tasks[0]["confidence"]
            except Exception:
                pass

            source_meta = meta.get("outlook") or meta.get("efundi") or {}
            is_automated_source = isinstance(source_meta, dict) and bool(source_meta.get("source"))
            if not include_unmapped and not mapped_tasks and is_automated_source and not meta.get("user_enhanced"):
                hidden_unmapped_count += 1
                continue

            file_path = evd.get("file_path")
            filename = meta.get("filename") or (Path(file_path).name if file_path else None)
            display_key = (
                str(file_path or filename or evd["evidence_id"]).lower(),
                str(top_task_id or meta.get("target_task_id") or "").lower(),
                str(meta.get("task") or "").lower(),
            )
            if display_key in seen_evidence_keys:
                hidden_unmapped_count += 1
                continue
            seen_evidence_keys.add(display_key)

            # Extract rating from brain scorer if available
            brain_data = meta.get("brain", {})
            rating = brain_data.get("rating") if isinstance(brain_data, dict) else None
            rating_label = brain_data.get("rating_label", "") if isinstance(brain_data, dict) else ""
            user_enhanced = meta.get("user_enhanced", False)
            feedback = _brain_feedback_fields(meta)
            
            evidence_list.append({
                "evidence_id": evd["evidence_id"],
                "staff_id": evd.get("staff_id"),
                "date": meta.get("date") or meta.get("timestamp") or "",
                "filename": filename or "",
                "kpa": evd.get("kpa_code") or "",
                "month": evd.get("month_bucket") or "",
                "task": top_task_title or meta.get("task") or "",
                "task_id": top_task_id or meta.get("target_task_id") or "",
                "mapped_tasks": mapped_tasks,
                "mapped_count": len(mapped_tasks),
                "tier": evd.get("tier") or meta.get("tier") or "",
                "impact_summary": meta.get("impact_summary") or "",
                "confidence": top_conf if top_conf is not None else float(meta.get("confidence") or 0.0),
                "rating": rating,
                "rating_label": rating_label,
                **feedback,
                "user_enhanced": user_enhanced,
                "brain": brain_data,
                "meta": meta,
                "file_path": file_path or "",
            })

        evidence_list.sort(
            key=lambda item: (
                int(item.get("mapped_count") or 0) <= 0,
                -float(item.get("confidence") or 0.0),
                str(item.get("date") or ""),
            )
        )
        include_all_evidence = str(request.args.get('include_all_evidence') or '').lower() in ('1', 'true', 'yes')
        if not include_all_evidence:
            capped = []
            per_task_counts = {}
            for item in evidence_list:
                task_key = item.get("task_id") or item.get("task") or item.get("evidence_id")
                count = per_task_counts.get(task_key, 0)
                if count >= 3:
                    hidden_unmapped_count += 1
                    continue
                per_task_counts[task_key] = count + 1
                capped.append(item)
            evidence_list = capped
        
        resp = {
            "progress": {
                "staff_id": staff_id,
                "year": int(year),
                "months": months,
                "total_tasks": int(progress.get("expected_tasks", 0)),
                "completed_count": int(progress.get("completed_tasks", 0)),
                "missing_tasks": progress.get("missing_tasks", []),
                "by_kpa": progress.get("by_kpa", {}),
                "hidden_unmapped_evidence": hidden_unmapped_count,
            },
            "evidence": evidence_list,
            "task_completion": task_completion,
            "stats": {
                "total_tasks": int(progress.get("expected_tasks", 0)),
                "completed_tasks": int(progress.get("completed_tasks", 0)),
                "evidence_count": len(evidence_list)
            }
        }

        # Always include months_progress for year-level requests (frontend expects this key)
        if not month:
            resp["months_progress"] = months_progress

        return jsonify(resp)
    
    except Exception as e:
        print(f"Progress error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/expectations/rebuild', methods=['POST'])
def rebuild_expectations():
    """
    Rebuild expectations from existing contract
    """
    try:
        data = request.json or {}
        staff_id = data.get('staff_id')
        year = data.get('year')
        
        if not staff_id or not year:
            return jsonify({"error": "Missing staff_id or year"}), 400
        
        # Prefer the parsed TA summary. The enrolment contract only contains
        # profile context and is not rich enough to rebuild expectation tasks.
        ta_file = CONTRACTS_FOLDER / f"ta_summary_{staff_id}_{year}.json"
        contract_file = CONTRACTS_FOLDER / f"contract_{staff_id}_{year}.json"
        source_file = ta_file if ta_file.exists() else contract_file

        if not source_file.exists():
            return jsonify({"error": "TA summary/contract not found. Import TA first."}), 404

        with open(source_file, 'r') as f:
            contract_data = json.load(f)
        
        # Build expectations
        if EXPECTATION_ENGINE_AVAILABLE and build_expectations_from_ta:
            expectations = build_expectations_from_ta(staff_id, int(year), contract_data)
            
            # Save expectations
            expectations_file = CONTRACTS_FOLDER.parent / "staff_expectations" / f"expectations_{staff_id}_{year}.json"
            expectations_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(expectations_file, 'w') as f:
                json.dump(expectations, f, indent=2)
            # Immediately ensure tasks are present in the progress DB
            try:
                from progress_store import ProgressStore
                from mapper import ensure_tasks
                store = ProgressStore()
                ensure_tasks(store, staff_id=staff_id, year=int(year), expectations=expectations)
            except Exception as e:
                print(f"Warning: could not upsert tasks after rebuild: {e}")
            
            return jsonify({
                "status": "success",
                "tasks_count": len(expectations.get('tasks', [])),
                "kpas_count": len(expectations.get('kpa_summary', {})),
                "work_context_applied": expectations.get("work_context_applied", {}),
                "message": f"Rebuilt {len(expectations.get('tasks', []))} tasks"
            })
        else:
            return jsonify({"error": "Expectation engine not available"}), 500
    
    except Exception as e:
        print(f"Rebuild error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/expectations', methods=['GET'])
def get_expectations():
    """
    Get Phase A expectations for a staff member
    """
    try:
        staff_id = request.args.get('staff_id')
        year = request.args.get('year')
        
        if not staff_id or not year:
            return jsonify({"error": "Missing parameters"}), 400
        
        # Try to load expectations file
        expectations_file = CONTRACTS_FOLDER.parent / "staff_expectations" / f"expectations_{staff_id}_{year}.json"
        
        if expectations_file.exists():
            with open(expectations_file, 'r') as f:
                expectations_data = json.load(f)

            # Add hashed task IDs to match progress system
            if TASK_MAP_AVAILABLE and 'tasks' in expectations_data:
                task_index: Dict[str, Dict[str, Any]] = {}
                for task in expectations_data['tasks']:
                    task_id = task.get('task_id') or task.get('id')
                    if not task_id:
                        continue
                    task_index[task_id] = task

                    if 'id' in task and 'months' in task:
                        # Generate hashed IDs for each month this task appears in
                        task['hashed_ids'] = {}
                        for month in task.get('months', []):
                            try:
                                month_int = int(month)
                                hashed_id = _hid(staff_id, str(year), str(task['id']), f"{month_int:02d}")
                                task['hashed_ids'][str(month)] = hashed_id
                            except (ValueError, TypeError):
                                continue

                # Update by_month structure to use hashed IDs
                if 'by_month' in expectations_data:
                    for month_key, month_data in expectations_data['by_month'].items():
                        if not isinstance(month_data, dict):
                            continue
                        month_tasks = month_data.get('tasks') or []
                        parts = month_key.split('-')
                        month_num = parts[1] if len(parts) > 1 else None
                        month_lookup = str(int(month_num)) if month_num else None

                        for task in month_tasks:
                            base_id = task.get('task_id') or task.get('id')
                            base_task = task_index.get(base_id) if base_id else None
                            hashed_id = None
                            if base_task and month_lookup and 'hashed_ids' in base_task:
                                hashed_id = base_task['hashed_ids'].get(month_lookup)

                            # Always set canonical hashed ID if available, else fallback to base ID
                            task['id'] = hashed_id or base_id
                            task['_baseId'] = base_id
                            task['_canonicalId'] = hashed_id

                            # Normalize field names for UI
                            if 'title' not in task and 'output' in task:
                                task['title'] = task['output']
                            task['minimum_count'] = task.get('min_required') or task.get('minimum_count') or 1
                            task['stretch_count'] = task.get('stretch_target') or task.get('stretch_count') or task['minimum_count']

                # Build a top-level id_map for deterministic lookups (hashed_id -> base_id)
                id_map: Dict[str, str] = {}
                mapping_warnings: List[str] = []
                collision_map: Dict[str, List[str]] = {}
                for base_id, base_task in task_index.items():
                    hashed_ids = base_task.get('hashed_ids') or {}
                    if not isinstance(hashed_ids, dict) or not hashed_ids:
                        mapping_warnings.append(f"No hashed_ids for base task {base_id}")
                        continue
                    for mon, hid in (hashed_ids.items() if isinstance(hashed_ids, dict) else []):
                        if not hid:
                            mapping_warnings.append(f"Empty hashed id for {base_id} month {mon}")
                            continue
                        # detect collisions
                        if hid in id_map and id_map[hid] != base_id:
                            collision_map.setdefault(hid, []).extend([id_map[hid], base_id])
                            mapping_warnings.append(f"Collision: hashed id {hid} maps to multiple base ids ({id_map[hid]}, {base_id})")
                        id_map[str(hid)] = base_id

                # Attach id_map and task_index for frontend diagnostics
                expectations_data['_id_map'] = id_map
                # Provide a lightweight task_index for quick lookups (base_id -> title)
                expectations_data['_task_index'] = {k: {'title': v.get('title') or v.get('output') or '', 'kpa_code': v.get('kpa_code')} for k, v in task_index.items()}
                # Attach mapping warnings for visibility
                if mapping_warnings:
                    expectations_data['_mapping_warnings'] = mapping_warnings
                    # persist warnings to file
                    try:
                        log_dir = CONTRACTS_FOLDER.parent / 'logs'
                        log_dir.mkdir(parents=True, exist_ok=True)
                        warn_file = log_dir / f'mapping_warnings_{staff_id}_{year}.log'
                        with open(warn_file, 'a') as wf:
                            import datetime as _dt
                            wf.write(f"---- { _dt.datetime.utcnow().isoformat() } UTC ----\n")
                            for w in mapping_warnings:
                                wf.write(w + "\n")
                            wf.write("\n")
                    except Exception as _e:
                        print(f"Could not persist mapping warnings: {_e}")
                if collision_map:
                    expectations_data['_mapping_collisions'] = {k: list(set(v)) for k, v in collision_map.items()}
                    try:
                        log_dir = CONTRACTS_FOLDER.parent / 'logs'
                        log_dir.mkdir(parents=True, exist_ok=True)
                        coll_file = log_dir / f'mapping_collisions_{staff_id}_{year}.log'
                        with open(coll_file, 'a') as cf:
                            import datetime as _dt
                            cf.write(f"---- { _dt.datetime.utcnow().isoformat() } UTC ----\n")
                            for hid, bases in collision_map.items():
                                cf.write(f"{hid} -> {set(bases)}\n")
                            cf.write("\n")
                    except Exception as _e:
                        print(f"Could not persist mapping collisions: {_e}")

            # Cache the expectations for quick lookups by other endpoints
            try:
                expectations_cache[(staff_id, year)] = expectations_data
                print(f"Cached expectations for {staff_id}/{year}")
            except Exception as _e:
                print(f"Could not cache expectations: {_e}")
            # Return the full expectations structure with tasks and by_month
            return jsonify(expectations_data)

        # If expectations file not found, require explicit import
        return jsonify({"error": "Expectations not found. Please import a Task Agreement via /api/ta/import."}), 404
    
    except Exception as e:
        print(f"Expectations error: {e}")
        return jsonify({"error": str(e)}), 500

def generate_mock_expectations():
    """Generate mock expectations for development"""
    return [
        {
            "id": "exp_001",
            "kpa": "Teaching & Learning",
            "task": "Develop new curriculum materials",
            "month": "2025-01",
            "enabler": "Academic freedom",
            "goal": "Enhanced student learning",
            "lead_target": "3 modules completed",
            "lag_target": "90% student satisfaction",
            "weight": 20,
            "progress": 65
        },
        {
            "id": "exp_002",
            "kpa": "Teaching & Learning",
            "task": "Supervise postgraduate students",
            "month": "2025-02",
            "enabler": "Research capacity",
            "goal": "Student progression",
            "lead_target": "5 students supervised",
            "lag_target": "80% completion rate",
            "weight": 15,
            "progress": 40
        },
        {
            "id": "exp_003",
            "kpa": "Research",
            "task": "Publish peer-reviewed article",
            "month": "2025-03",
            "enabler": "Research time allocation",
            "goal": "Academic contribution",
            "lead_target": "1 article submitted",
            "lag_target": "Published in accredited journal",
            "weight": 25,
            "progress": 30
        },
        {
            "id": "exp_004",
            "kpa": "Research",
            "task": "Attend academic conference",
            "month": "2025-04",
            "enabler": "Conference funding",
            "goal": "Networking & dissemination",
            "lead_target": "1 paper presented",
            "lag_target": "3 new collaborations",
            "weight": 10,
            "progress": 0
        }
    ]

@app.route('/api/expectations/check-month', methods=['POST'])
def check_month_completion():
    """
    Check if a month's expectations have been met based on uploaded evidence
    Uses VAMP AI to analyze completion status
    """
    try:
        data = request.json
        staff_id = data.get('staff_id')
        month = data.get('month')  # Format: "2025-01"
        
        if not staff_id or not month:
            return jsonify({"error": "Missing staff_id or month"}), 400
        
        year = month.split('-')[0]
        
        # Load expectations for this month
        contract_file = CONTRACTS_FOLDER / f"contract_{staff_id}_{year}.json"
        expectations_file = CONTRACTS_FOLDER.parent / "staff_expectations" / f"expectations_{staff_id}_{year}.json"
        
        month_tasks = []
        expectations_data = None
        if expectations_file.exists():
            with open(expectations_file, 'r') as f:
                expectations_data = json.load(f)
                by_month = expectations_data.get('by_month', {})
                month_tasks = by_month.get(month, [])
        
        # Use progress store to get accurate per-task evidence counts
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from progress_store import ProgressStore
        from mapper import ensure_tasks
        
        store = ProgressStore()

        # Prefer canonical tasks from the DB for this staff/month so that hashed/DB task_ids
        # used by asserted/targeted mappings are matched correctly.
        try:
            # Ensure the DB catalog exists for this staff/year
            ensure_tasks(store, staff_id=staff_id, year=int(year), expectations=expectations_data)

            month_num = int(month.split('-')[1])
            db_rows = store.list_tasks_for_window(int(year), [month_num], kpa_code=None)
            # Always use DB-derived month tasks (canonical task_ids)
            month_tasks = []
            for r in db_rows:
                row = dict(r)
                month_tasks.append({
                    'id': row.get('task_id'),
                    'kpa_code': row.get('kpa_code'),
                    'title': row.get('title'),
                    'minimum_count': row.get('min_required') or row.get('minimum_count') or row.get('min_required', 0)
                })
        except Exception:
            # If DB lookup fails, fall back to expectations file contents already loaded
            pass
        
        # Get evidence mapped to tasks for this month
        evidence_count = 0
        evidence_by_task = {}
        task_status = []
        
        # Query evidence for this staff/year/month from progress store
        try:
            con = store._connect()
            cur = con.cursor()
            
            # Get unique evidence count
            cur.execute("""
                SELECT COUNT(DISTINCT e.evidence_id)
                FROM evidence e
                WHERE e.staff_id = ? AND e.year = ? AND e.month_bucket LIKE ?
            """, (staff_id, int(year), f"{month}%"))
            evidence_count = cur.fetchone()[0]
            
            # Get evidence mapped to tasks (with distinct evidence per task)
            cur.execute("""
                SELECT et.task_id, COUNT(DISTINCT et.evidence_id) as count
                FROM evidence e
                JOIN evidence_task et ON e.evidence_id = et.evidence_id
                WHERE e.staff_id = ? AND e.year = ? AND e.month_bucket LIKE ?
                GROUP BY et.task_id
            """, (staff_id, int(year), f"{month}%"))
            
            for row in cur:
                task_id = row[0]
                count = row[1]
                evidence_by_task[task_id] = count
            
            con.close()
        except Exception as e:
            print(f"Error querying evidence: {e}")
            import traceback
            traceback.print_exc()
        
        # Calculate per-task completion
        tasks_met = 0
        tasks_total = len(month_tasks)
        
        for task in month_tasks:
            # Normalize task identifier fields coming from different expectation file formats
            task_id = task.get('id') or task.get('task_id') or task.get('hashed_id') or task.get('task')
            # Normalize minimum required field (various names used in expectations payloads)
            min_required = task.get('minimum_count') or task.get('min_required') or task.get('minimum_count') or 0
            try:
                min_required = int(min_required or 0)
            except Exception:
                min_required = 0

            task_evidence_count = evidence_by_task.get(task_id, 0)
            task_met = task_evidence_count >= min_required

            if task_met:
                tasks_met += 1

            task_status.append({
                'task_id': task_id,
                'kpa_code': task.get('kpa_code') or task.get('kpa') or 'Unknown',
                'title': task.get('title') or task.get('output') or task.get('task') or 'Task',
                'evidence_count': task_evidence_count,
                'minimum_required': min_required,
                'met': task_met
            })
        
        # Month is complete if all tasks with min_required > 0 are met
        required_tasks = [t for t in task_status if t['minimum_required'] > 0]
        # Month is only complete when all required tasks are met (no evidence-only shortcut)
        complete = bool(required_tasks) and all(t['met'] for t in required_tasks)
        
        # Build AI analysis prompt
        ai_context = {
            'staff_id': staff_id,
            'month': month,
            'tasks_total': tasks_total,
            'tasks_met': tasks_met,
            'evidence_count': evidence_count,
            'task_status': task_status
        }
        
        # Try to get AI analysis, but don't fail if Ollama is unavailable
        # Provide natural conversational messages
        import random
        name = data.get('name') or 'there'
        if complete:
            success_msgs = [
                f"Excellent work, {name}! You've nailed all {tasks_met} tasks for {month}. That's {evidence_count} pieces of solid evidence. Time to lock this month and celebrate!",
                f"Hey {name}, you're all set for {month}! All {tasks_met} tasks are covered with {evidence_count} evidence items. Nice job — go ahead and lock it in.",
                f"{name}, {month} is looking great! You've hit every target with {evidence_count} evidence pieces across {tasks_met} tasks. Ready to finalize?"
            ]
            ai_response = random.choice(success_msgs)
        else:
            pending = tasks_total - tasks_met
            tasks_incomplete = [t for t in required_tasks if not t['met']]
            incomplete_sample = tasks_incomplete[:2]  # Show up to 2 examples
            incomplete_text = ""
            if incomplete_sample:
                incomplete_text = f" For example, {', '.join([f'{t['kpa_code']}: {t['title']}' for t in incomplete_sample])}."
            
            progress_msgs = [
                f"Hey {name}, you're making progress on {month}! {tasks_met} of {tasks_total} tasks done so far. {pending} more to go{incomplete_text} Upload more evidence or mark tasks as 'No Evidence' where applicable.",
                f"{name}, quick update for {month}: {tasks_met} tasks complete, {pending} still need attention{incomplete_text} Let's get those sorted out!",
                f"Looking at {month}, {name} — you're at {tasks_met}/{tasks_total} tasks{incomplete_text} Keep up the good work!"
            ]
            ai_response = random.choice(progress_msgs)
        
        # Try Ollama enhancement (optional)
        try:
            if complete:
                ai_prompt = f"The staff member has met all {tasks_met}/{tasks_total} required tasks for {month} with {evidence_count} evidence items. Provide brief encouragement (2 sentences max)."
            else:
                tasks_incomplete = [t for t in required_tasks if not t['met']]
                incomplete_details = ", ".join([f"{t['kpa_code']}: {t['title']} ({t['evidence_count']}/{t['minimum_required']})" for t in tasks_incomplete[:3]])
                ai_prompt = f"The staff member has only met {tasks_met}/{tasks_total} tasks for {month}. Incomplete tasks: {incomplete_details}. Provide brief constructive guidance (2 sentences max)."
            
            ollama_response = query_ollama(ai_prompt, ai_context)
            # Only use Ollama response if it doesn't contain error messages
            if ollama_response and not any(err in ollama_response for err in ["Cannot reach", "unavailable", "error occurred"]):
                ai_response = ollama_response
        except Exception as ollama_error:
            print(f"Ollama unavailable for AI review: {ollama_error}")
            # Keep the default fallback message set above
        
        # Build detailed per-task summary with visual indicators
        task_summary_lines = []
        for ts in task_status:
            if ts['minimum_required'] > 0:
                status_icon = "✓" if ts['met'] else "⚠"
                task_summary_lines.append(
                    f"{status_icon} {ts['kpa_code']}: {ts['title'][:50]} ({ts['evidence_count']}/{ts['minimum_required']} items)"
                )
        
        # Generate voice audio for the response
        audio_url = None
        try:
            if ELEVENLABS_AVAILABLE and text_to_speech and sanitize_for_speech:
                clean_text = sanitize_for_speech(ai_response)
                audio_path = text_to_speech(clean_text)
                if audio_path:
                    audio_url = f"/api/voice/audio/{audio_path.name}"
        except Exception as voice_err:
            print(f"Voice generation for month check failed: {voice_err}")
        
        return jsonify({
            "complete": complete,
            "tasks_met": tasks_met,
            "tasks_total": tasks_total,
            "evidence_count": evidence_count,
            "message": ai_response,
            "summary": "\n".join(task_summary_lines) if task_summary_lines else "No tasks for this month",
            "task_status": task_status,
            "missing": f"{tasks_total - tasks_met} tasks still need evidence" if not complete else "",
            "audio_url": audio_url
        })
    
    except Exception as e:
        print(f"Month check error: {e}")
        return jsonify({"error": str(e)}), 500


# ============================================================
# MONTH LOCKING & NO-EVIDENCE DECLARATIONS
# ============================================================

_RISK_REVIEW_CATEGORIES = {
    "deadline_or_delivery": {
        "terms": [
            "lateness",
            "overdue",
            "missed deadline",
            "deadline missed",
            "late submission",
            "submitted late",
            "late report",
            "delayed",
            "delay",
            "extension",
            "not submitted",
            "outstanding",
            "pending",
            "follow up",
            "follow-up",
        ],
        "label": "deadline/delivery context",
    },
    "complaint_or_escalation": {
        "terms": [
            "complaint",
            "grievance",
            "concern",
            "escalation",
            "disciplinary",
            "appeal",
            "query",
            "dissatisfied",
            "unhappy",
        ],
        "label": "complaint/escalation context",
    },
    "absence_or_capacity": {
        "terms": [
            "absence",
            "absent",
            "leave",
            "sick leave",
            "medical",
            "doctor",
            "appointment",
            "wellness",
            "employee wellness",
            "counselling",
            "mental health",
            "burnout",
            "capacity",
            "workload",
        ],
        "label": "absence/capacity/wellness context",
    },
    "compliance_or_safety": {
        "terms": [
            "non-compliance",
            "compliance issue",
            "compliance concern",
            "compliance risk",
            "risk",
            "ohs",
            "safety",
            "security",
            "incident",
            "hazard",
            "popia",
            "dalro",
            "audit",
            "access",
            "campus entry",
        ],
        "label": "compliance/safety context",
    },
}


def _risk_review_for_month(store, staff_id: str, year: int, month: str) -> Dict[str, Any]:
    """Build a humane pre-lock review of possible context/risk signals.

    This is intentionally not a punitive scorer. It flags signals that may need
    an explanation or supporting evidence before the month becomes immutable.
    """
    evidence_rows = [dict(row) for row in store.list_evidence(staff_id, year, month_bucket=month)]
    no_evidence_rows = store.get_no_evidence_tasks(staff_id, year, month)
    findings: list[dict] = []

    def _add_findings(source: str, title: str, text: str, ref: str = "") -> None:
        lowered = (text or "").lower()
        for category, cfg in _RISK_REVIEW_CATEGORIES.items():
            hits = []
            for term in cfg["terms"]:
                term_l = term.lower()
                pattern = r"(?<![a-z0-9])" + re.escape(term_l).replace(r"\ ", r"\s+") + r"(?![a-z0-9])"
                if re.search(pattern, lowered):
                    hits.append(term)
            if not hits:
                continue
            findings.append(
                {
                    "category": category,
                    "label": cfg["label"],
                    "source": source,
                    "title": title[:180],
                    "reference": ref,
                    "matched_terms": sorted(set(hits))[:8],
                    "preview": re.sub(r"\s+", " ", text or "")[:320],
                    "tone": "context_needed",
                }
            )

    for row in evidence_rows:
        meta = {}
        try:
            meta = json.loads(row.get("meta_json") or "{}")
        except Exception:
            meta = {}
        parts = [
            row.get("file_path", ""),
            meta.get("filename", ""),
            meta.get("subject", ""),
            meta.get("title", ""),
            meta.get("impact_summary", ""),
            meta.get("assessment_summary", ""),
            meta.get("user_explanation", ""),
            meta.get("body_preview", ""),
            meta.get("row_preview", ""),
        ]
        _add_findings("evidence", meta.get("subject") or meta.get("filename") or Path(row.get("file_path", "")).name, " ".join(str(p or "") for p in parts), row.get("evidence_id", ""))

    for item in no_evidence_rows:
        _add_findings(
            "no_evidence_declaration",
            item.get("task_id", "No-evidence declaration"),
            item.get("reason", ""),
            item.get("task_id", ""),
        )

    categories = sorted({finding["category"] for finding in findings})
    supportive_terms = {"medical", "doctor", "wellness", "leave", "counselling", "mental health", "employee wellness"}
    has_support_context = any(
        any(term in " ".join(finding.get("matched_terms") or []) for term in supportive_terms)
        for finding in findings
    )
    return {
        "month": month,
        "reviewed_sources": {
            "evidence_items": len(evidence_rows),
            "no_evidence_declarations": len(no_evidence_rows),
        },
        "finding_count": len(findings),
        "categories": categories,
        "findings": findings[:20],
        "has_support_or_wellness_context": has_support_context,
        "requires_acknowledgement": True,
        "summary": (
            "No obvious risk/compliance/context signals were found in the currently ingested evidence. "
            "Still confirm that there are no known complaints, absences, missed deadlines, or compliance matters before locking."
            if not findings
            else "VAMP found possible risk/context signals. This is not punitive: add a short explanation or supporting evidence before locking so the record is fair and honest."
        ),
        "recommended_context_prompt": (
            "If anything affected delivery this month, briefly explain the context and point to supporting evidence such as approved leave, medical documentation, wellness appointments, revised deadlines, or remedial actions."
        ),
    }


@app.route('/api/month/risk-review', methods=['POST'])
def month_risk_review():
    try:
        data = request.json or {}
        staff_id = data.get('staff_id')
        month = data.get('month')
        if not staff_id or not month:
            return jsonify({"error": "Missing staff_id or month"}), 400
        year = int(month.split('-')[0])
        from progress_store import ProgressStore
        store = ProgressStore()
        return jsonify({"success": True, "risk_review": _risk_review_for_month(store, staff_id, year, month)})
    except Exception as e:
        print(f"Month risk review error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/month/lock', methods=['POST'])
def lock_month():
    """Lock a month after all tasks are completed or declared."""
    try:
        data = request.json
        staff_id = data.get('staff_id')
        month = data.get('month')
        risk_review_ack = bool(data.get('risk_review_ack'))
        risk_context_note = str(data.get('risk_context_note') or '').strip()
        
        if not staff_id or not month:
            return jsonify({"error": "Missing staff_id or month"}), 400
        
        year = int(month.split('-')[0])
        
        from progress_store import ProgressStore
        store = ProgressStore()
        
        # Check if already locked
        if store.is_month_locked(staff_id, year, month):
            return jsonify({"error": "Month is already locked", "locked": True}), 400

        risk_review = _risk_review_for_month(store, staff_id, year, month)
        if not risk_review_ack:
            return jsonify({
                "error": "Risk/context review required before locking",
                "risk_review_required": True,
                "risk_review": risk_review,
            }), 409
        
        # Get month completion status first
        month_num = int(month.split('-')[1])
        
        # Count tasks and evidence for this month
        db_rows = store.list_tasks_for_window(year, [month_num])
        tasks_total = len(db_rows)
        
        # Get evidence count
        con = store._connect()
        try:
            cur = con.execute("""
                SELECT COUNT(DISTINCT et.task_id) as completed,
                       COUNT(DISTINCT e.evidence_id) as evidence
                FROM evidence e
                LEFT JOIN evidence_task et ON e.evidence_id = et.evidence_id
                WHERE e.staff_id = ? AND e.year = ? AND e.month_bucket LIKE ?
            """, (staff_id, year, f"{month}%"))
            row = cur.fetchone()
            tasks_completed = row[0] if row else 0
            evidence_count = row[1] if row else 0
        finally:
            con.close()
        
        # Also count no-evidence declarations
        no_evidence_tasks = store.get_no_evidence_tasks(staff_id, year, month)
        no_evidence_count = len(no_evidence_tasks)
        
        # Verify all tasks are accounted for (either evidence or no-evidence)
        task_ids_with_evidence = set()
        con = store._connect()
        try:
            cur = con.execute("""
                SELECT DISTINCT et.task_id
                FROM evidence e
                JOIN evidence_task et ON e.evidence_id = et.evidence_id
                WHERE e.staff_id = ? AND e.year = ? AND e.month_bucket LIKE ?
            """, (staff_id, year, f"{month}%"))
            for row in cur:
                task_ids_with_evidence.add(row[0])
        finally:
            con.close()
        
        no_evidence_task_ids = set(t['task_id'] for t in no_evidence_tasks)
        all_task_ids = set(r['task_id'] for r in db_rows)
        accounted_tasks = task_ids_with_evidence | no_evidence_task_ids
        
        missing_tasks = all_task_ids - accounted_tasks
        if missing_tasks:
            return jsonify({
                "error": "Cannot lock month - some tasks are not completed or marked as no-evidence",
                "missing_count": len(missing_tasks),
                "missing_task_ids": list(missing_tasks)[:5]  # Show first 5
            }), 400
        
        # Lock the month
        store.lock_month(
            staff_id, year, month,
            tasks_completed=len(task_ids_with_evidence),
            tasks_total=tasks_total,
            evidence_count=evidence_count,
            risk_review=risk_review,
            risk_context_note=risk_context_note,
        )
        return jsonify({
            "success": True,
            "message": f"Month {month} locked successfully",
            "stats": {
                "tasks_with_evidence": len(task_ids_with_evidence),
                "tasks_no_evidence": no_evidence_count,
                "tasks_total": tasks_total,
                "evidence_count": evidence_count
            }
        })
        
    except Exception as e:
        print(f"Month lock error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/month/unlock', methods=['POST'])
def unlock_month():
    """Unlock a previously locked month."""
    try:
        data = request.json
        staff_id = data.get('staff_id')
        month = data.get('month')
        
        if not staff_id or not month:
            return jsonify({"error": "Missing staff_id or month"}), 400
        
        year = int(month.split('-')[0])
        
        from progress_store import ProgressStore
        store = ProgressStore()
        
        if store.unlock_month(staff_id, year, month):
            return jsonify({"success": True, "message": f"Month {month} unlocked"})
        else:
            return jsonify({"error": "Month was not locked"}), 400
            
    except Exception as e:
        print(f"Month unlock error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/month/status', methods=['GET'])
def get_month_lock_status():
    """Get lock status for all months."""
    try:
        staff_id = request.args.get('staff_id')
        year = request.args.get('year')
        
        if not staff_id or not year:
            return jsonify({"error": "Missing staff_id or year"}), 400
        
        from progress_store import ProgressStore
        store = ProgressStore()
        
        locked_months = store.get_locked_months(staff_id, int(year))
        
        return jsonify({
            "staff_id": staff_id,
            "year": int(year),
            "locked_months": locked_months
        })
        
    except Exception as e:
        print(f"Month status error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/task/no-evidence', methods=['POST'])
def declare_task_no_evidence():
    """Declare that a task has no evidence available."""
    try:
        data = request.json
        staff_id = data.get('staff_id')
        task_id = data.get('task_id')
        month = data.get('month')
        reason = data.get('reason', '')
        
        if not staff_id or not task_id or not month:
            return jsonify({"error": "Missing staff_id, task_id, or month"}), 400
        
        year = int(month.split('-')[0])
        
        from progress_store import ProgressStore
        store = ProgressStore()
        
        # Check if month is locked
        if store.is_month_locked(staff_id, year, month):
            return jsonify({"error": "Cannot modify - month is locked"}), 400
        
        store.declare_no_evidence(staff_id, year, task_id, month, reason)
        
        return jsonify({
            "success": True,
            "message": f"Task marked as no evidence available"
        })
        
    except Exception as e:
        print(f"No evidence error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/task/no-evidence', methods=['DELETE'])
def remove_task_no_evidence():
    """Remove a no-evidence declaration."""
    try:
        data = request.json
        staff_id = data.get('staff_id')
        task_id = data.get('task_id')
        month = data.get('month')
        
        if not staff_id or not task_id or not month:
            return jsonify({"error": "Missing staff_id, task_id, or month"}), 400
        
        year = int(month.split('-')[0])
        
        from progress_store import ProgressStore
        store = ProgressStore()
        
        # Check if month is locked
        if store.is_month_locked(staff_id, year, month):
            return jsonify({"error": "Cannot modify - month is locked"}), 400
        
        if store.remove_no_evidence(staff_id, year, task_id, month):
            return jsonify({"success": True, "message": "No-evidence declaration removed"})
        else:
            return jsonify({"error": "Declaration not found"}), 404
        
    except Exception as e:
        print(f"Remove no evidence error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/task/no-evidence/list', methods=['GET'])
def list_no_evidence_tasks():
    """List all tasks declared as having no evidence."""
    try:
        staff_id = request.args.get('staff_id')
        year = request.args.get('year')
        month = request.args.get('month')  # Optional
        
        if not staff_id or not year:
            return jsonify({"error": "Missing staff_id or year"}), 400
        
        from progress_store import ProgressStore
        store = ProgressStore()
        
        tasks = store.get_no_evidence_tasks(staff_id, int(year), month)
        
        return jsonify({
            "staff_id": staff_id,
            "year": int(year),
            "month": month,
            "no_evidence_tasks": tasks
        })
        
    except Exception as e:
        print(f"List no evidence error: {e}")
        return jsonify({"error": str(e)}), 500


# ============================================================
# MID-YEAR REVIEW AGGREGATION
# ============================================================

@app.route('/api/review/midyear', methods=['POST'])
def generate_midyear_review():
    """Generate mid-year review aggregating Jan-June data."""
    try:
        data = request.json
        staff_id = data.get('staff_id')
        year = data.get('year')
        
        if not staff_id or not year:
            return jsonify({"error": "Missing staff_id or year"}), 400
        
        year = int(year)
        midyear_months = [f"{year}-{m:02d}" for m in range(1, 7)]  # Jan-June
        
        from progress_store import ProgressStore
        store = ProgressStore()
        
        # Check which months are locked
        locked_months = store.get_locked_months(staff_id, year)
        locked_month_set = set(m['month'] for m in locked_months)
        
        unlocked = [m for m in midyear_months if m not in locked_month_set]
        if unlocked:
            return jsonify({
                "error": "Cannot generate mid-year review - not all months are locked",
                "unlocked_months": unlocked,
                "message": f"Please lock months: {', '.join(unlocked)}"
            }), 400
        
        # Aggregate data from Jan-June
        aggregate = {
            "staff_id": staff_id,
            "year": year,
            "review_type": "midyear",
            "period": "January - June",
            "months": midyear_months,
            "by_month": {},
            "by_kpa": {},
            "totals": {
                "tasks_completed": 0,
                "tasks_total": 0,
                "tasks_no_evidence": 0,
                "evidence_count": 0,
                "completion_rate": 0.0
            }
        }
        
        # Get per-month stats from locked data
        for lock in locked_months:
            if lock['month'] in midyear_months:
                aggregate["by_month"][lock['month']] = {
                    "tasks_completed": lock['tasks_completed'],
                    "tasks_total": lock['tasks_total'],
                    "evidence_count": lock['evidence_count'],
                    "locked_at": lock['locked_at']
                }
                aggregate["totals"]["tasks_completed"] += lock['tasks_completed']
                aggregate["totals"]["tasks_total"] += lock['tasks_total']
                aggregate["totals"]["evidence_count"] += lock['evidence_count']
        
        # Get no-evidence count
        no_evidence = store.get_no_evidence_tasks(staff_id, year)
        midyear_no_evidence = [t for t in no_evidence if t['month'] in midyear_months]
        aggregate["totals"]["tasks_no_evidence"] = len(midyear_no_evidence)
        
        # Calculate completion rate
        total = aggregate["totals"]["tasks_total"]
        completed = aggregate["totals"]["tasks_completed"] + aggregate["totals"]["tasks_no_evidence"]
        aggregate["totals"]["completion_rate"] = round(100.0 * completed / total, 1) if total > 0 else 0.0
        
        # Get KPA breakdown
        month_nums = list(range(1, 7))
        for month_num in month_nums:
            month_key = f"{year}-{month_num:02d}"
            db_rows = store.list_tasks_for_window(year, [month_num])
            
            for row in db_rows:
                kpa = row['kpa_code']
                if kpa not in aggregate["by_kpa"]:
                    aggregate["by_kpa"][kpa] = {
                        "tasks_total": 0,
                        "tasks_completed": 0,
                        "completion_rate": 0.0
                    }
                aggregate["by_kpa"][kpa]["tasks_total"] += 1
        
        # Count completed tasks by KPA
        con = store._connect()
        try:
            for month_num in month_nums:
                month_key = f"{year}-{month_num:02d}"
                cur = con.execute("""
                    SELECT t.kpa_code, COUNT(DISTINCT et.task_id) as completed
                    FROM evidence e
                    JOIN evidence_task et ON e.evidence_id = et.evidence_id
                    JOIN tasks t ON t.task_id = et.task_id
                    WHERE e.staff_id = ? AND e.year = ? AND e.month_bucket LIKE ?
                    GROUP BY t.kpa_code
                """, (staff_id, year, f"{month_key}%"))
                
                for row in cur:
                    kpa = row[0]
                    if kpa in aggregate["by_kpa"]:
                        aggregate["by_kpa"][kpa]["tasks_completed"] += row[1]
        finally:
            con.close()
        
        # Calculate KPA completion rates
        for kpa, stats in aggregate["by_kpa"].items():
            if stats["tasks_total"] > 0:
                stats["completion_rate"] = round(100.0 * stats["tasks_completed"] / stats["tasks_total"], 1)
        
        # Generate AI summary
        try:
            summary_prompt = f"""Generate a brief mid-year performance review summary for a staff member:
- Period: January to June {year}
- Tasks Completed: {aggregate['totals']['tasks_completed']} of {aggregate['totals']['tasks_total']}
- Tasks Marked No Evidence: {aggregate['totals']['tasks_no_evidence']}
- Evidence Items: {aggregate['totals']['evidence_count']}
- Overall Completion: {aggregate['totals']['completion_rate']}%

Provide 2-3 sentences of constructive feedback. Write in plain text, no markdown."""
            
            ai_summary = query_ollama(summary_prompt)
            if ai_summary and "Cannot reach" not in ai_summary and "error" not in ai_summary.lower():
                aggregate["ai_summary"] = ai_summary
            else:
                aggregate["ai_summary"] = f"Mid-year review complete. {aggregate['totals']['tasks_completed']} tasks completed with {aggregate['totals']['evidence_count']} evidence items across January-June."
        except Exception:
            aggregate["ai_summary"] = f"Mid-year review complete. {aggregate['totals']['tasks_completed']} tasks completed with {aggregate['totals']['evidence_count']} evidence items across January-June."
        
        # Save the snapshot
        store.save_review_snapshot(staff_id, year, "midyear", midyear_months, aggregate)
        
        return jsonify(aggregate)
        
    except Exception as e:
        print(f"Mid-year review error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/review/midyear', methods=['GET'])
def get_midyear_review():
    """Get existing mid-year review if available."""
    try:
        staff_id = request.args.get('staff_id')
        year = request.args.get('year')
        
        if not staff_id or not year:
            return jsonify({"error": "Missing staff_id or year"}), 400
        
        from progress_store import ProgressStore
        store = ProgressStore()
        
        snapshot = store.get_review_snapshot(staff_id, int(year), "midyear")
        
        if snapshot:
            return jsonify(snapshot["summary"])
        else:
            return jsonify({"exists": False, "message": "No mid-year review generated yet"})
        
    except Exception as e:
        print(f"Get mid-year review error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/review/status', methods=['GET'])
def get_review_status():
    """Get status of mid-year and end-year reviews."""
    try:
        staff_id = request.args.get('staff_id')
        year = request.args.get('year')
        
        if not staff_id or not year:
            return jsonify({"error": "Missing staff_id or year"}), 400
        
        year = int(year)
        
        from progress_store import ProgressStore
        store = ProgressStore()
        
        # Get locked months
        locked = store.get_locked_months(staff_id, year)
        locked_months = set(m['month'] for m in locked)
        
        # Check mid-year readiness (Jan-June)
        midyear_months = [f"{year}-{m:02d}" for m in range(1, 7)]
        midyear_locked = [m for m in midyear_months if m in locked_months]
        midyear_ready = len(midyear_locked) == 6
        
        # Check end-year readiness (Jul-Dec)
        endyear_months = [f"{year}-{m:02d}" for m in range(7, 13)]
        endyear_locked = [m for m in endyear_months if m in locked_months]
        endyear_ready = len(endyear_locked) == 6 and midyear_ready
        
        # Get existing reviews
        midyear_review = store.get_review_snapshot(staff_id, year, "midyear")
        endyear_review = store.get_review_snapshot(staff_id, year, "endyear")
        
        return jsonify({
            "staff_id": staff_id,
            "year": year,
            "midyear": {
                "ready": midyear_ready,
                "locked_count": len(midyear_locked),
                "required_count": 6,
                "months_locked": midyear_locked,
                "months_unlocked": [m for m in midyear_months if m not in locked_months],
                "review_exists": midyear_review is not None,
                "review_date": midyear_review["created_at"] if midyear_review else None
            },
            "endyear": {
                "ready": endyear_ready,
                "locked_count": len(endyear_locked),
                "required_count": 6,
                "months_locked": endyear_locked,
                "months_unlocked": [m for m in endyear_months if m not in locked_months],
                "review_exists": endyear_review is not None,
                "review_date": endyear_review["created_at"] if endyear_review else None
            }
        })
        
    except Exception as e:
        print(f"Review status error: {e}")
        return jsonify({"error": str(e)}), 500


# ============================================================
# EVIDENCE SCANNING
# ============================================================

@app.route('/api/scan/upload', methods=['POST'])
def scan_upload():
    """
    Upload and scan evidence files with AI classification
    """
    try:
        if 'files' not in request.files:
            return jsonify({"error": "No files uploaded"}), 400
        
        files = request.files.getlist('files')
        staff_id = request.form.get('staff_id')
        month = request.form.get('month')
        target_task_id = request.form.get('target_task_id') or None
        use_brain = request.form.get('use_brain') == 'true'
        use_contextual = request.form.get('use_contextual') == 'true'
        asserted_mapping = request.form.get('asserted_mapping') == 'true'  # User pre-locked evidence to task
        user_explanation = request.form.get('user_explanation', '').strip()  # User's explanation for locked evidence

        # Allow target_task_id without explicit assertion for soft-linking;
        # asserted_mapping upgrades the mapping to user-confirmed/locked status.
        
        results = []
        
        # Brain scorer is function-based (no NWUBrainScorer class)
        brain_enabled = bool(use_brain and BRAIN_SCORER_AVAILABLE and brain_score_evidence is not None)
        
        for idx, file in enumerate(files, 1):
            try:
                filename = secure_filename(file.filename)
                filepath = UPLOAD_FOLDER / filename
                file.save(str(filepath))
                
                # Extract text from file with detailed logging
                file_text = ""
                extraction_method = "unknown"
                try:
                    file_text = extract_text_from_file(str(filepath))
                    text_length = len(file_text.strip())
                    extraction_method = "vamp_master" if text_length > 50 else "minimal"
                    print(f"[SCAN] {filename}: extracted {text_length} chars via {extraction_method}")
                except Exception as e:
                    print(f"[SCAN ERROR] Text extraction failed for {filename}: {e}")
                    import traceback
                    traceback.print_exc()
                    file_text = f"File: {filename}"
                    extraction_method = "failed"
                
                # Prepare user-impact text; still run AI + brain scoring even when asserted
                impact_text = None
                if asserted_mapping and target_task_id:
                    impact_text = "Evidence directly linked to task by user (asserted relevance)"
                    if user_explanation:
                        impact_text = f"User explanation: {user_explanation[:200]}... | {impact_text}"

                # AI Classification using Ollama (use contextual if requested)
                if use_contextual:
                    try:
                        classification = classify_with_ollama(filename, file_text)
                    except Exception as e:
                        print(f"Ollama classification failed for {filename}: {e}")
                        # Fallback classification
                        classification = {
                            "kpa": "Unclassified",
                            "task": "Needs manual review",
                            "tier": "N/A",
                            "impact_summary": f"Classification failed: {str(e)[:100]}",
                            "confidence": 0.3
                        }
                else:
                    classification = {
                        "kpa": "Teaching & Learning",
                        "task": "General teaching activity",
                        "tier": "Tier 2",
                        "impact_summary": "Documented teaching evidence",
                        "confidence": 0.75
                    }

                # Prepend user impact text if present so user assertions are visible in meta
                if impact_text:
                    try:
                        classification["impact_summary"] = f"{impact_text} | {classification.get('impact_summary','') }"
                    except Exception:
                        pass

                # Deterministic NWU Brain scoring (prioritize this for accuracy)
                # Skip brain scorer if user has asserted the mapping to respect their decision
                brain_ctx = None
                # Always run brain scoring when available to produce rating/tier, even for asserted mappings
                if brain_enabled:
                    try:
                        brain_ctx = brain_score_evidence(path=Path(filepath), full_text=file_text, kpa_hint_code=None)
                        # Update classification with brain scorer results if more confident
                        if brain_ctx:
                            # Brain scorer provides deterministic KPA routing
                            old_kpa = classification.get("kpa")
                            classification["kpa"] = brain_ctx.get("primary_kpa_name", classification.get("kpa"))
                            classification["tier"] = brain_ctx.get("tier_label", classification.get("tier"))
                            
                            # Boost confidence significantly when brain scorer has high route scores
                            kpa_scores = brain_ctx.get("kpa_route_scores", {})
                            max_score = max(kpa_scores.values()) if kpa_scores else 0
                            old_conf = classification.get("confidence", 0.5)
                            
                            if max_score >= 2.0:
                                classification["confidence"] = 0.85
                            elif max_score >= 1.0:
                                classification["confidence"] = 0.70
                            else:
                                classification["confidence"] = max(0.55, old_conf)
                            
                            # Log brain scorer decision
                            print(f"[BRAIN] {filename}: {brain_ctx.get('primary_kpa_code')} "
                                  f"(score={max_score:.1f}, conf={classification['confidence']:.2f}, "
                                  f"tier={classification['tier']})")
                            if old_kpa != classification["kpa"]:
                                print(f"[BRAIN] KPA changed: {old_kpa} → {classification['kpa']}")
                            
                            # Enhance impact summary with brain insights
                            values_hits = brain_ctx.get("values_hits", [])
                            policy_hits = brain_ctx.get("policy_hits", [])
                            tier_label = brain_ctx.get("tier_label", "")
                            rating = brain_ctx.get("rating", 0)
                            
                            # Build richer impact summary
                            impact_parts = [classification["impact_summary"]]
                            
                            if tier_label:
                                impact_parts.append(f"Tier: {tier_label}")
                            
                            if rating:
                                impact_parts.append(f"Rating: {rating:.1f}/5.0")
                            
                            if values_hits:
                                impact_parts.append(f"Demonstrates: {', '.join(values_hits[:3])}")
                            
                            if policy_hits:
                                policy_names = [p.get("name", "") for p in policy_hits[:2] if isinstance(p, dict)]
                                if policy_names:
                                    impact_parts.append(f"Policies: {', '.join(policy_names)}")
                            
                            classification["impact_summary"] = " | ".join(impact_parts)
                    except Exception as e:
                        print(f"[BRAIN ERROR] Brain scorer failed for {filename}: {e}")
                        import traceback
                        traceback.print_exc()
                        brain_ctx = None

                    # Also request a richer Ollama classification (longer, structured JSON)
                    ai_ctx = None
                    if use_contextual:
                        try:
                            print(f"[OLLAMA] Requesting detailed classification for {filename}")
                            # Build a prompt that prioritises the user's explanation when present
                            prompt = f"""Provide a JSON classification for this evidence file.
    Include fields: kpa (human-friendly), task, tier, impact_summary, confidence (0.0-1.0).

    USER_EXPLANATION: {user_explanation or ''}
    FILENAME: {filename}
    CONTENT_PREVIEW: {file_text[:2000]}

    Return only valid JSON."""
                            try:
                                ai_ctx = classify_with_ollama_raw(prompt)
                            except Exception as e:
                                print(f"[OLLAMA ERROR] classify_with_ollama_raw failed for {filename}: {e}")
                                ai_ctx = None

                            if ai_ctx:
                                try:
                                    print(f"[OLLAMA] Response for {filename}: {str(ai_ctx)[:400]}")
                                    # Merge AI classification into the existing classification
                                    # Brain scorer remains authoritative for rating/tier when present
                                    classification["kpa"] = ai_ctx.get("kpa", classification.get("kpa"))
                                    classification["task"] = ai_ctx.get("task", classification.get("task"))
                                    # Only override tier if brain did not provide a tier
                                    if not brain_ctx:
                                        classification["tier"] = ai_ctx.get("tier", classification.get("tier"))
                                    # Blend confidence
                                    classification["confidence"] = max(classification.get("confidence", 0.0), float(ai_ctx.get("confidence", 0.0)))
                                    # Build an enhanced impact summary combining user, AI and brain
                                    classification["impact_summary"] = _build_enhanced_impact_summary(
                                        user_description=user_explanation or "",
                                        ai_summary=ai_ctx.get("impact_summary", classification.get("impact_summary","")),
                                        brain_ctx=brain_ctx,
                                        filename=filename,
                                        tier=classification.get("tier", "")
                                    )
                                except Exception as e:
                                    print(f"[OLLAMA MERGE ERROR] {e}")
                        except Exception as e:
                            print(f"[OLLAMA ERROR] Detailed Ollama classification failed for {filename}: {e}")
                            ai_ctx = None

                    # Ensure we always persist a meaningful `ollama` entry.
                    if not ai_ctx:
                        # Build a richer fallback from user + brain + classification so UI shows something meaningful
                        try:
                            enhanced_summary = _build_enhanced_impact_summary(
                                user_description=user_explanation or "",
                                ai_summary=classification.get("impact_summary", ""),
                                brain_ctx=brain_ctx,
                                filename=filename,
                                tier=classification.get("tier", "")
                            )
                            ai_ctx = {
                                "kpa": classification.get("kpa"),
                                "task": classification.get("task"),
                                "tier": classification.get("tier"),
                                "impact_summary": enhanced_summary,
                                "confidence": float(classification.get("confidence", 0.0)),
                                "fallback": True,
                            }
                            print(f"[OLLAMA FALLBACK] Using enriched fallback AI ctx for {filename}")
                        except Exception:
                            ai_ctx = {"impact_summary": classification.get("impact_summary", ""), "fallback": True}

                    # Map KPA name to KPA code (from brain first, else from Ollama classification)
                # Use exact matching to avoid false positives (e.g., "teaching" in "teaching practice")
                kpa_code = None
                if brain_ctx and brain_ctx.get("primary_kpa_code"):
                    kpa_code = str(brain_ctx.get("primary_kpa_code"))
                if not kpa_code:
                    kpa_lower = classification.get("kpa", "").lower().strip()
                    
                    # Exact match prioritized by specificity (longest first)
                    kpa_patterns = [
                        (["teaching & learning", "teaching and learning"], "KPA1"),
                        (["occupational health & safety", "occupational health and safety", "ohs"], "KPA2"),
                        (["research, innovation & creative outputs", "research & innovation", "research and innovation", "research"], "KPA3"),
                        (["academic leadership & administration", "leadership & administration", "academic leadership", "leadership"], "KPA4"),
                        (["social responsiveness", "community engagement", "social responsibility"], "KPA5"),
                    ]
                    
                    kpa_code = "KPA1"  # default
                    for patterns, code in kpa_patterns:
                        if kpa_lower in patterns:
                            kpa_code = code
                            break
                
                # Store in progress database
                evidence_id = None
                mapped_tasks = []
                try:
                    import sys
                    sys.path.insert(0, str(Path(__file__).parent))
                    from progress_store import ProgressStore
                    from mapper import ensure_tasks, map_evidence_to_tasks
                    import hashlib
                    
                    # Initialize progress store
                    store = ProgressStore()
                    
                    # Ensure we have a per-month task catalog before mapping.
                    # Without this, mapping may silently produce 0 links (no candidates).
                    try:
                        expectations_file = CONTRACTS_FOLDER.parent / "staff_expectations" / f"expectations_{staff_id}_{month[:4]}.json"
                        expectations_data = None
                        if expectations_file.exists():
                            with open(expectations_file, 'r', encoding='utf-8') as f:
                                expectations_data = json.load(f)
                        ensure_tasks(store, staff_id=staff_id, year=int(month[:4]), expectations=expectations_data)
                    except Exception:
                        try:
                            ensure_tasks(store, staff_id=staff_id, year=int(month[:4]), expectations=None)
                        except Exception:
                            pass
                    
                    # Generate evidence ID (avoid collisions when filenames repeat)
                    # Use content sha1 prefix to be unique-per-content and idempotent on re-scan.
                    sha1 = hashlib.sha1(file_text.encode(errors="ignore")).hexdigest()
                    evidence_id = f"ev_{staff_id}_{month}_{sha1[:10]}"
                    
                    # If a target task was provided AND it's an assertion, override KPA from task
                    # This must happen BEFORE evidence insertion to ensure correct KPA is stored
                    if target_task_id and asserted_mapping:
                        try:
                            task_row = None
                            for r in store.list_tasks_for_window(int(month[:4]), [int(month.split('-')[1])], kpa_code=None):
                                if r["task_id"] == target_task_id:
                                    task_row = r
                                    break
                            if task_row is not None:
                                # Override KPA code to match the target task's KPA
                                kpa_code = task_row["kpa_code"]
                                print(f"[ASSERTION] Overriding KPA to {kpa_code} based on target task {target_task_id}")
                        except Exception as e:
                            print(f"[ASSERTION WARNING] Could not extract KPA from target task: {e}")

                    # Insert evidence
                    store.insert_evidence(
                        evidence_id=evidence_id,
                        sha1=sha1,
                        staff_id=staff_id,
                        year=int(month[:4]),
                        month_bucket=month,
                        kpa_code=kpa_code,
                        rating=(brain_ctx.get("rating_label") if brain_ctx else classification.get("tier")),
                        tier=(brain_ctx.get("tier_label") if brain_ctx else classification.get("tier")),
                        file_path=str(filepath),
                        meta={
                            "filename": filename,
                            "date": datetime.utcnow().date().isoformat(),
                            "timestamp": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
                            "impact_summary": classification["impact_summary"],
                            "user_explanation": user_explanation if user_explanation else None,
                            "confidence": classification["confidence"],
                            "task": classification["task"],
                            "target_task_id": target_task_id or "",
                            "brain": brain_ctx or {},
                            "ollama": ai_ctx or {},
                        }
                    )

                    # If we used a fallback Ollama result, schedule background retries
                    try:
                        if ai_ctx and isinstance(ai_ctx, dict) and ai_ctx.get("fallback"):
                            import threading
                            thread = threading.Thread(
                                target=_retry_ollama_and_update,
                                args=(
                                    evidence_id,
                                    filename,
                                    file_text,
                                    user_explanation or "",
                                    staff_id,
                                    int(month[:4]),
                                    month,
                                ),
                            )
                            thread.daemon = True
                            thread.start()
                            print(f"[OLLAMA RETRY] Scheduled background retry for {evidence_id}")
                    except Exception as e:
                        print(f"[OLLAMA RETRY] Failed to schedule retry thread: {e}")
                    
                    # Map evidence to tasks
                    # Skip generic mapping if user has asserted a specific task (respect user decision)
                    if asserted_mapping and target_task_id:
                        # User has locked evidence to a specific task - skip generic mapping
                        mapped_tasks = []
                        print(f"[ASSERTION] Skipping generic mapping - evidence locked to task {target_task_id}")
                    else:
                        # Perform generic mapping based on KPA, text signals, etc.
                        mapped_tasks = map_evidence_to_tasks(
                            store,
                            evidence_id=evidence_id,
                            staff_id=staff_id,
                            year=int(month[:4]),
                            month_bucket=month,
                            kpa_code=kpa_code,
                            meta={
                                "filename": filename,
                                "impact_summary": classification["impact_summary"],
                                "evidence_type": classification["task"]
                            },
                            mapped_by="web_scan:v1"
                        )

                    # Targeted mapping (high confidence) - apply AFTER generic mapping
                    if target_task_id:
                        try:
                            # Mark as asserted if user explicitly locked evidence to task
                            mapped_by_value = "web_scan:targeted:asserted" if asserted_mapping else "web_scan:targeted"
                            store.upsert_mapping(
                                evidence_id,
                                target_task_id,
                                mapped_by=mapped_by_value,
                                confidence=0.95,
                            )
                            # Ensure UI acknowledges mapping immediately (scan results use mapped_tasks length)
                            try:
                                # Get the actual task title from the store
                                task_title = "Targeted task"
                                try:
                                    for r in store.list_tasks_for_window(int(month[:4]), [int(month.split('-')[1])], kpa_code=None):
                                        if r["task_id"] == target_task_id:
                                            task_title = r.get("title", "Targeted task")
                                            break
                                except Exception:
                                    pass
                                
                                mapped_tasks.append(
                                    {
                                        "task_id": target_task_id,
                                        "kpa_code": kpa_code,
                                        "title": task_title,
                                        "confidence": 0.95,
                                        "relevance_source": "asserted" if asserted_mapping else "targeted",
                                    }
                                )
                            except Exception:
                                pass
                        except Exception:
                            pass
                    
                except Exception as db_error:
                    print(f"Progress store error for {filename}: {db_error}")
                    import traceback
                    traceback.print_exc()
                
                # Store result
                result = {
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "file": filename,
                    "kpa": classification["kpa"],
                    "kpa_code": kpa_code,
                    "task": classification["task"],
                    "tier": classification["tier"],
                    "rating": brain_ctx.get("rating") if brain_ctx else None,
                    "rating_label": brain_ctx.get("rating_label") if brain_ctx else "",
                    "impact_summary": classification["impact_summary"],
                    "confidence": classification["confidence"],
                    "status": "Classified" if classification["confidence"] >= 0.6 else "Needs Review",
                    "evidence_id": evidence_id,
                    "mapped_tasks": mapped_tasks,  # Full array with task IDs, titles, and confidence
                    "mapped_count": len(mapped_tasks),  # Keep count for backward compatibility
                    "brain": brain_ctx or {}  # Include full brain scorer results
                }
                
                results.append(result)
                
                # Send event to connected clients
                send_event({
                    "type": "file_scanned",
                    "file": filename,
                    "current": idx,
                    "total": len(files)
                })
                
            except Exception as file_error:
                print(f"Error processing file {file.filename}: {file_error}")
                # Add error result
                results.append({
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "file": file.filename,
                    "kpa": "Error",
                    "task": "Processing failed",
                    "tier": "N/A",
                    "impact_summary": str(file_error)[:200],
                    "confidence": 0.0,
                    "status": "Error"
                })
        
        # Send completion event
        send_event({
            "type": "scan_finished",
            "total": len(results)
        })
        
        return jsonify({"results": results})
    
    except Exception as e:
        print(f"Scan error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/outlook/collect', methods=['POST'])
def collect_outlook_evidence():
    """Collect month-targeted evidence candidates from Outlook Web and ingest them into VAMP."""
    try:
        if not OUTLOOK_COLLECTOR_AVAILABLE or collect_outlook_candidates is None:
            return jsonify({"error": "Outlook collector is unavailable. Ensure Playwright dependencies are installed."}), 500

        data = request.json or {}
        staff_id = str(data.get('staff_id') or '').strip()
        month = str(data.get('month') or '').strip()
        mode = str(data.get('mode') or 'month_all_tasks').strip()
        task_ids_requested = data.get('task_ids') or []
        max_messages = max(1, min(int(data.get('max_messages') or 12), 50))
        include_body_only = bool(data.get('include_body_only_candidates', True))
        include_calendar_events = bool(data.get('include_calendar_events', True))
        headless = bool(data.get('headless', False))

        if not staff_id or not month:
            return jsonify({"error": "Missing staff_id or month"}), 400

        # month may be "2", "02", or "2026-02"
        _month_parts = month.split('-')
        if len(_month_parts) >= 2 and len(_month_parts[0]) == 4:
            _year_from_month, _month_num_str = int(_month_parts[0]), _month_parts[1]
        else:
            _year_from_month, _month_num_str = None, _month_parts[-1]
        year = int(data.get('year') or _year_from_month or datetime.now().year)

        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from progress_store import ProgressStore
        from mapper import ensure_tasks, map_evidence_to_tasks
        import hashlib

        store = ProgressStore()

        expectations_file = CONTRACTS_FOLDER.parent / 'staff_expectations' / f'expectations_{staff_id}_{year}.json'
        expectations_data = None
        if expectations_file.exists():
            with open(expectations_file, 'r', encoding='utf-8') as f:
                expectations_data = json.load(f)

        ensure_tasks(store, staff_id=staff_id, year=year, expectations=expectations_data)

        month_num = int(_month_num_str)
        task_rows = [dict(row) for row in store.list_tasks_for_window(year, [month_num], kpa_code=None)]
        if not task_rows:
            return jsonify({"error": f"No expectation tasks found for {month}"}), 404

        evidence_counts: dict[str, int] = {}
        if mode == 'incomplete_tasks':
            con = store._connect()
            try:
                cur = con.execute(
                    """
                    SELECT et.task_id, COUNT(DISTINCT et.evidence_id) as count
                    FROM evidence e
                    JOIN evidence_task et ON e.evidence_id = et.evidence_id
                    WHERE e.staff_id = ? AND e.year = ? AND e.month_bucket LIKE ?
                    GROUP BY et.task_id
                    """,
                    (staff_id, year, f"{month}%"),
                )
                evidence_counts = {row[0]: int(row[1]) for row in cur.fetchall()}
            finally:
                con.close()

        plans = []
        for row in task_rows:
            task_id = row.get('task_id')
            if task_ids_requested and task_id not in task_ids_requested:
                continue
            min_required = int(row.get('min_required') or 0)
            current_count = int(evidence_counts.get(task_id, 0))
            if mode == 'incomplete_tasks' and min_required > 0 and current_count >= min_required:
                continue
            try:
                hints_payload = json.loads(row.get('hints_json') or '{}')
            except Exception:
                hints_payload = {}
            hints = [str(item).strip() for item in (hints_payload.get('hints') or []) if str(item).strip()]

            # Enrich with KPA-specific evidence keywords so searches target the RIGHT emails.
            # These are terms that actually appear in Outlook emails Byron would receive as evidence.
            _KPA_OUTLOOK_KEYWORDS: dict[str, list[str]] = {
                'KPA1': [
                    'eFundi', 'HISE312', 'HISE411', 'ERTP671', 'LERP671',
                    'assessment', 'marks', 'moderation', 'lecture', 'student',
                    'teaching practice', 'WIL', 'study guide', 'gradebook',
                ],
                'KPA2': [
                    'OHS', 'safety', 'POPIA', 'compliance', 'audit',
                ],
                'KPA3': [
                    'research', 'supervision', 'postgraduate', 'publication',
                    'article', 'journal', 'Citesaga', 'WorkReady', 'AI GBL',
                    'conference', 'NRF',
                ],
                'KPA4': [
                    'committee', 'minutes', 'agenda', 'meeting',
                    'Faculty Board', 'school management', 'SMC',
                    'academic', 'circular', 'policy',
                ],
            }
            kpa = row.get('kpa_code') or ''
            kpa_extras = _KPA_OUTLOOK_KEYWORDS.get(kpa, [])
            title_l = (row.get('title') or '').lower()
            if kpa == 'KPA1' and any(marker in title_l for marker in ('ror', 'orientation', 'reception', 'registration')):
                kpa_extras = [
                    'ROR', 'orientation', 'orientation programme',
                    'student orientation', 'registration', 'reception',
                    'welcome',
                ]
            elif kpa == 'KPA1' and any(marker in title_l for marker in ('jan:', 'efundi', 'study guide', 'reading list', 'assessment planning', 'module planning')):
                kpa_extras = [
                    'eFundi', 'announcement', 'content upload', 'study unit',
                    'resources', 'study guide', 'reading list', 'rubric',
                    'assessment plan', 'module plan',
                ]
            elif kpa == 'KPA3' and any(marker in title_l for marker in ('supervision', 'postgraduate')):
                kpa_extras = [
                    'postgraduate', 'supervision', 'supervisor', 'supervisee',
                    'MEd', 'PhD', 'proposal', 'thesis', 'dissertation',
                    'ethics', 'progress meeting',
                ]
            elif kpa == 'KPA3' and 'workready' in title_l:
                kpa_extras = [
                    'WorkReady', 'work-ready', 'work readiness', 'work-readiness',
                    'intervention', 'ethics', 'publication', 'article', 'manuscript',
                    'project planning', 'project status',
                ]
            elif kpa == 'KPA3' and ('citesaga' in title_l or 'cite saga' in title_l):
                kpa_extras = [
                    'Citesaga', 'CiteSaga', 'cite saga', 'citation game',
                    'book chapter', 'AOSIS', 'publication', 'article', 'manuscript',
                    'InfoEd', 'project status',
                ]
            elif kpa == 'KPA3' and any(marker in title_l for marker in ('ai and gbl', 'ai gbl', 'gbl project')):
                kpa_extras = [
                    'AI GBL', 'AI and GBL', 'game-based learning', 'game based learning',
                    'game based pedagogy', 'gamified learning', 'gamification',
                    'play-based learning', 'play based learning', 'playful learning',
                    'serious games', 'educational game', 'learning game',
                    'VAMP', 'SERAPH', 'AI project', 'AI system', 'artificial intelligence',
                    'agentic AI', 'LLM', 'prototype', 'software prototype',
                    'invention disclosure', 'technology disclosure', 'IP disclosure',
                    'D2026', 'D2026-164', 'tech transfer', 'commercialisation',
                    'intervention', 'ethics', 'publication', 'article', 'manuscript',
                    'project status',
                ]
            elif kpa == 'KPA3' and 'professional development' in title_l:
                kpa_extras = [
                    'research workshop', 'writing school', 'webinar', 'seminar',
                    'training', 'professional development', 'NRF',
                ]
            elif kpa == 'KPA3' and 'publication' in title_l:
                kpa_extras = [
                    'publication', 'article', 'journal', 'manuscript', 'draft',
                    'conference', 'Citesaga', 'WorkReady', 'AI GBL', 'Prosper',
                ]
            elif kpa == 'KPA4' and 'committee' in title_l:
                kpa_extras = [
                    'minutes', 'agenda', 'meeting', 'committee', 'Teams meeting',
                    'Faculty Forum', 'Mentorship', 'School Management',
                    'SMC', 'Subject Group', 'Research Focus Area',
                    'professional development',
                ]
            # Merge: task-specific hints first (they're more precise), then KPA extras for coverage
            merged_keywords = hints[:]
            for kw in kpa_extras:
                if kw.lower() not in {h.lower() for h in merged_keywords}:
                    merged_keywords.append(kw)

            plans.append(
                {
                    'task_id': task_id,
                    'kpa_code': kpa,
                    'title': row.get('title', ''),
                    'keywords': merged_keywords,
                    'min_required': min_required,
                }
            )

        if not plans:
            return jsonify({"error": f"No target tasks available for Outlook collection in {month}"}), 404

        profile_terms = _profile_context_terms(staff_id, year)
        if profile_terms:
            for plan in plans:
                existing = {str(kw).lower() for kw in (plan.get('context_terms') or [])}
                for term in profile_terms:
                    if term.lower() not in existing:
                        plan.setdefault('context_terms', []).append(term)
                        existing.add(term.lower())

        search_diagnostics = []
        if describe_search_plan_queries is not None:
            try:
                search_diagnostics = describe_search_plan_queries(plans, month_bucket=month)
            except Exception:
                search_diagnostics = []

        outlook_state_dir = DATA_FOLDER / 'outlook'
        outlook_state_dir.mkdir(parents=True, exist_ok=True)
        safe_staff_id = secure_filename(staff_id) or staff_id.replace('/', '-').replace('\\', '-')
        staff_outlook_dir = outlook_state_dir / safe_staff_id
        staff_outlook_dir.mkdir(parents=True, exist_ok=True)
        storage_state = str(staff_outlook_dir / f'state_{year}.json')
        downloads_dir = str(staff_outlook_dir / 'downloads')

        candidates = collect_outlook_candidates(
            month_bucket=month,
            search_plans=plans,
            storage_state=storage_state,
            downloads_dir=downloads_dir,
            max_messages=max_messages,
            headless=headless,
            include_body_only_candidates=include_body_only,
            include_calendar_events=include_calendar_events,
        )

        results = []
        rejected_candidates = []
        for candidate in candidates:
            attachment_paths = [path for path in (candidate.get('attachment_paths') or []) if path]
            body_artifact_path = candidate.get('body_artifact_path') or ''
            primary_path = attachment_paths[0] if attachment_paths else body_artifact_path
            if not primary_path:
                continue

            text_parts = [
                candidate.get('subject', ''),
                candidate.get('sender', ''),
                candidate.get('recipients', ''),
                candidate.get('received_at', ''),
                candidate.get('body_text', ''),
                ' '.join(candidate.get('attachment_names') or []),
            ]
            for attachment_path in attachment_paths:
                try:
                    text_parts.append(extract_text_from_file(attachment_path))
                except Exception:
                    continue
            file_text = '\n'.join(part for part in text_parts if part)

            brain_ctx = None
            if BRAIN_SCORER_AVAILABLE and brain_score_evidence is not None:
                try:
                    brain_ctx = brain_score_evidence(
                        path=Path(primary_path),
                        full_text=file_text,
                        kpa_hint_code=candidate.get('kpa_hint_code'),
                    )
                except Exception as brain_error:
                    print(f"[OUTLOOK] Brain scoring failed for {primary_path}: {brain_error}")

            sha1 = hashlib.sha1(file_text.encode(errors='ignore')).hexdigest()
            evidence_id = f"ev_{staff_id}_{month}_{sha1[:10]}"
            had_task_candidates = bool(candidate.get('task_candidates'))
            selected_task_ids = _selected_outlook_task_ids(candidate, task_ids_requested)
            if not selected_task_ids:
                rejected_candidates.append({
                    'subject': candidate.get('subject', ''),
                    'source': candidate.get('source', ''),
                    'reason': 'No strong task-level match after relevance gating',
                    'search_reason': candidate.get('search_reason') or '',
                    'matched_tasks': candidate.get('matched_tasks') or [],
                })
                continue
            # Outlook collection is launched from a concrete task/KPA search plan.
            # Prefer that targeted KPA for routing; the brain scorer can still
            # provide rating/tier, but should not override the known search target.
            kpa_code = candidate.get('kpa_hint_code') or (brain_ctx or {}).get('primary_kpa_code') or ''
            impact_summary = candidate.get('search_reason') or 'Collected from Outlook for targeted monthly evidence search.'
            source_context = candidate.get('source_context') or {}
            source_boost = float(source_context.get('confidence_boost') or 0.0)
            confidence = min(0.98, (0.9 if candidate.get('task_candidates') else 0.55) + source_boost)

            store.insert_evidence(
                evidence_id=evidence_id,
                sha1=sha1,
                staff_id=staff_id,
                year=year,
                month_bucket=month,
                kpa_code=kpa_code,
                rating=((brain_ctx or {}).get('rating_label') or ''),
                tier=((brain_ctx or {}).get('tier_label') or ''),
                file_path=str(primary_path),
                meta={
                    'filename': Path(primary_path).name,
                    'date': datetime.utcnow().date().isoformat(),
                    'timestamp': datetime.utcnow().replace(microsecond=0).isoformat() + 'Z',
                    'impact_summary': impact_summary,
                    'confidence': confidence,
                    'task': candidate.get('evidence_type_hint') or 'outlook_message',
                    'source_context': source_context,
                    'target_task_id': selected_task_ids[0] if selected_task_ids else '',
                    'brain': brain_ctx or {},
                    'outlook': {
                        'staff_id': staff_id,
                        'source': candidate.get('source'),
                        'source_message_id': candidate.get('source_message_id'),
                        'source_url': candidate.get('source_url'),
                        'subject': candidate.get('subject'),
                        'sender': candidate.get('sender'),
                        'recipients': candidate.get('recipients'),
                        'received_at': candidate.get('received_at'),
                        'attachment_names': candidate.get('attachment_names') or [],
                        'attachment_paths': attachment_paths,
                        'matched_tasks': candidate.get('matched_tasks') or [],
                        'search_reason': candidate.get('search_reason') or '',
                        'source_context': source_context,
                    },
                },
            )

            mapped_tasks = []
            if not selected_task_ids and not had_task_candidates:
                mapped_tasks = map_evidence_to_tasks(
                    store,
                    evidence_id=evidence_id,
                    staff_id=staff_id,
                    year=year,
                    month_bucket=month,
                    kpa_code=kpa_code,
                    meta={
                        'filename': Path(primary_path).name,
                        'impact_summary': impact_summary,
                        'evidence_type': candidate.get('evidence_type_hint') or 'outlook_message',
                        'summary': candidate.get('body_text') or '',
                        'snippet': candidate.get('subject', ''),
                    },
                    mapped_by='outlook_collect:v1',
                )

            for matched_task_id in selected_task_ids:
                try:
                    store.upsert_mapping(
                        evidence_id,
                        matched_task_id,
                        mapped_by='outlook_collect:targeted',
                        confidence=0.9,
                    )
                except Exception:
                    continue

            try:
                mapped_tasks = [
                    {
                        "task_id": m["task_id"],
                        "kpa_code": m["kpa_code"],
                        "title": m["title"],
                        "confidence": float(m["confidence"] or 0.0),
                        "mapped_by": m["mapped_by"],
                    }
                    for m in store.list_mappings_for_evidence(evidence_id)
                ]
            except Exception:
                mapped_tasks = mapped_tasks or []

            results.append(
                {
                    'date': datetime.utcnow().strftime('%Y-%m-%d'),
                    'file': Path(primary_path).name,
                    'evidence_id': evidence_id,
                    'kpa_code': kpa_code,
                    'tier': (brain_ctx or {}).get('tier_label', ''),
                    'rating': (brain_ctx or {}).get('rating'),
                    'rating_label': (brain_ctx or {}).get('rating_label', ''),
                    'impact_summary': impact_summary,
                    'confidence': confidence,
                    'source_context': source_context,
                    'status': 'Collected',
                    'mapped_tasks': mapped_tasks,
                    'mapped_count': len(mapped_tasks),
                    'subject': candidate.get('subject', ''),
                    'source': 'outlook_playwright',
                }
            )

        return jsonify(
            {
                'success': True,
                'month': month,
                'mode': mode,
                'results': results,
                'collected_count': len(results),
                'rejected_count': len(rejected_candidates),
                'rejected_candidates': rejected_candidates[:25],
                'search_diagnostics': search_diagnostics,
                'storage_state': storage_state,
            }
        )
    except Exception as e:
        print(f"Outlook collect error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/efundi/collect', methods=['POST'])
def collect_efundi_evidence():
    """Collect direct eFundi/LMS evidence for module-linked monthly tasks."""
    try:
        if not EFUNDI_COLLECTOR_AVAILABLE or collect_efundi_candidates is None:
            return jsonify({"error": "eFundi collector is unavailable. Ensure Playwright dependencies are installed."}), 500

        data = request.json or {}
        staff_id = str(data.get('staff_id') or '').strip()
        month = str(data.get('month') or '').strip()
        task_ids_requested = data.get('task_ids') or []
        max_items = max(1, min(int(data.get('max_items') or data.get('max_messages') or 20), 50))
        headless = bool(data.get('headless', False))

        if not staff_id or not month:
            return jsonify({"error": "Missing staff_id or month"}), 400

        _month_parts = month.split('-')
        if len(_month_parts) >= 2 and len(_month_parts[0]) == 4:
            _year_from_month, _month_num_str = int(_month_parts[0]), _month_parts[1]
        else:
            _year_from_month, _month_num_str = None, _month_parts[-1]
        year = int(data.get('year') or _year_from_month or datetime.now().year)
        month_num = int(_month_num_str)

        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from progress_store import ProgressStore
        from mapper import ensure_tasks
        import hashlib

        store = ProgressStore()
        expectations_file = CONTRACTS_FOLDER.parent / 'staff_expectations' / f'expectations_{staff_id}_{year}.json'
        expectations_data = None
        if expectations_file.exists():
            with open(expectations_file, 'r', encoding='utf-8') as f:
                expectations_data = json.load(f)
        ensure_tasks(store, staff_id=staff_id, year=year, expectations=expectations_data)

        task_rows = [dict(row) for row in store.list_tasks_for_window(year, [month_num], kpa_code='KPA1')]
        plans = []
        for row in task_rows:
            task_id = row.get('task_id')
            if task_ids_requested and task_id not in task_ids_requested:
                continue
            try:
                hints_payload = json.loads(row.get('hints_json') or '{}')
            except Exception:
                hints_payload = {}
            hints = [str(item).strip() for item in (hints_payload.get('hints') or []) if str(item).strip()]
            title = row.get('title') or ''
            if not any(marker in title.upper() for marker in ('HISE', 'ERTP', 'LERP', 'SSCE')):
                continue
            merged = hints[:]
            for kw in ['eFundi', 'LMS', 'module site', 'announcement', 'resources', 'assignment', 'gradebook', 'assessment']:
                if kw.lower() not in {h.lower() for h in merged}:
                    merged.append(kw)
            plans.append({
                'task_id': task_id,
                'kpa_code': row.get('kpa_code') or 'KPA1',
                'title': title,
                'keywords': merged,
                'min_required': int(row.get('min_required') or 0),
            })

        if not plans:
            return jsonify({"error": f"No module-linked KPA1 tasks found for eFundi collection in {month}"}), 404

        profile_terms = _profile_context_terms(staff_id, year)
        if profile_terms:
            for plan in plans:
                existing = {str(kw).lower() for kw in (plan.get('context_terms') or [])}
                for term in profile_terms:
                    if term.lower() not in existing:
                        plan.setdefault('context_terms', []).append(term)
                        existing.add(term.lower())

        efundi_state_dir = DATA_FOLDER / 'efundi'
        efundi_state_dir.mkdir(parents=True, exist_ok=True)
        safe_staff_id = secure_filename(staff_id) or staff_id.replace('/', '-').replace('\\', '-')
        staff_efundi_dir = efundi_state_dir / safe_staff_id
        staff_efundi_dir.mkdir(parents=True, exist_ok=True)
        storage_state = str(staff_efundi_dir / f'state_{year}.json')
        downloads_dir = str(staff_efundi_dir / 'downloads')

        candidates = collect_efundi_candidates(
            month_bucket=month,
            search_plans=plans,
            storage_state=storage_state,
            downloads_dir=downloads_dir,
            max_items=max_items,
            headless=headless,
        )

        results = []
        for candidate in candidates:
            attachment_paths = [path for path in (candidate.get('attachment_paths') or []) if path]
            body_artifact_path = candidate.get('body_artifact_path') or ''
            primary_path = body_artifact_path or (attachment_paths[0] if attachment_paths else '')
            if not primary_path:
                continue

            file_text = '\n'.join([
                candidate.get('subject', ''),
                candidate.get('sender', ''),
                candidate.get('received_at', ''),
                candidate.get('body_text', ''),
                ' '.join(candidate.get('attachment_names') or []),
            ])
            sha1 = hashlib.sha1(file_text.encode(errors='ignore')).hexdigest()
            evidence_id = f"ev_{staff_id}_{month}_{sha1[:10]}"
            selected_task_ids = _selected_outlook_task_ids(candidate, task_ids_requested)
            source_context = candidate.get('source_context') or {}
            confidence = min(0.98, 0.9 + float(source_context.get('confidence_boost') or 0.0))

            store.insert_evidence(
                evidence_id=evidence_id,
                sha1=sha1,
                staff_id=staff_id,
                year=year,
                month_bucket=month,
                kpa_code='KPA1',
                rating='',
                tier='',
                file_path=str(primary_path),
                meta={
                    'filename': Path(primary_path).name,
                    'date': datetime.utcnow().date().isoformat(),
                    'timestamp': datetime.utcnow().replace(microsecond=0).isoformat() + 'Z',
                    'impact_summary': candidate.get('search_reason') or 'Collected from direct eFundi/LMS module-site evidence.',
                    'confidence': confidence,
                    'task': candidate.get('evidence_type_hint') or 'efundi_lms_snapshot',
                    'source_context': source_context,
                    'target_task_id': selected_task_ids[0] if selected_task_ids else '',
                    'efundi': {
                        'staff_id': staff_id,
                        'source': candidate.get('source'),
                        'source_url': candidate.get('source_url'),
                        'subject': candidate.get('subject'),
                        'module_code': (candidate.get('meta') or {}).get('module_code'),
                        'attachment_names': candidate.get('attachment_names') or [],
                        'attachment_paths': attachment_paths,
                        'search_reason': candidate.get('search_reason') or '',
                    },
                },
            )

            for matched_task_id in selected_task_ids:
                try:
                    store.upsert_mapping(
                        evidence_id,
                        matched_task_id,
                        mapped_by='efundi_collect:direct_lms',
                        confidence=confidence,
                    )
                except Exception:
                    continue

            mapped_tasks = []
            try:
                mapped_tasks = [
                    {
                        "task_id": m["task_id"],
                        "kpa_code": m["kpa_code"],
                        "title": m["title"],
                        "confidence": float(m["confidence"] or 0.0),
                        "mapped_by": m["mapped_by"],
                    }
                    for m in store.list_mappings_for_evidence(evidence_id)
                ]
            except Exception:
                pass

            results.append({
                'date': datetime.utcnow().strftime('%Y-%m-%d'),
                'file': Path(primary_path).name,
                'evidence_id': evidence_id,
                'kpa_code': 'KPA1',
                'impact_summary': candidate.get('search_reason') or '',
                'confidence': confidence,
                'source_context': source_context,
                'status': 'Collected',
                'mapped_tasks': mapped_tasks,
                'mapped_count': len(mapped_tasks),
                'subject': candidate.get('subject', ''),
                'source': 'efundi_playwright',
            })

        return jsonify({
            'success': True,
            'month': month,
            'results': results,
            'collected_count': len(results),
            'storage_state': storage_state,
        })
    except Exception as e:
        print(f"eFundi collect error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

def extract_text_from_file(filepath: str) -> str:
    """
    Robust text extraction from various file types with OCR fallback.
    Supports: PDF, DOCX, XLSX, PPTX, TXT, MD, CSV, and images (PNG, JPG, TIFF, etc.)
    """
    try:
        from backend.vamp_master import extract_text_for
        result = extract_text_for(Path(filepath))
        
        # Log extraction issues
        if result.extract_status != "ok":
            print(f"[EXTRACTION] {filepath}: status={result.extract_status}, error={result.extract_error}")
        
        return result.extracted_text or f"File: {Path(filepath).name}"
    except Exception as e:
        print(f"[EXTRACTION ERROR] {filepath}: {e}")
        # Fallback to basic extraction
        ext = Path(filepath).suffix.lower()
        
        if ext == '.txt':
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    return f.read()
            except:
                pass
        
        elif ext == '.pdf':
            try:
                import PyPDF2
                with open(filepath, 'rb') as f:
                    reader = PyPDF2.PdfReader(f)
                    text = ""
                    for page in reader.pages:
                        text += page.extract_text() or ""
                    if text.strip():
                        return text
            except Exception as pdf_err:
                print(f"[PDF FALLBACK ERROR] {filepath}: {pdf_err}")
        
        return f"File: {Path(filepath).name} (extraction failed)"

def _build_enhanced_impact_summary(
    user_description: str,
    ai_summary: str,
    brain_ctx: Dict = None,
    filename: str = "",
    tier: str = ""
) -> str:
    """
    Build a comprehensive impact summary from multiple sources.
    Combines user description, AI classification, and brain scorer insights.
    """
    parts = []
    
    # Start with user description (most trusted)
    if user_description:
        parts.append(f"User: {user_description.strip()}")
    
    # Add AI-generated summary if different from user description
    if ai_summary and ai_summary.lower() not in user_description.lower():
        parts.append(f"Analysis: {ai_summary.strip()}")
    
    # Add brain scorer insights
    if brain_ctx:
        details = []
        
        # Rating and tier
        rating = brain_ctx.get("rating")
        tier_label = brain_ctx.get("tier_label")
        if rating:
            details.append(f"Rating {rating:.1f}/5.0")
        if tier_label:
            details.append(f"{tier_label}")
        
        # Values demonstrated
        values_hits = brain_ctx.get("values_hits", [])
        if values_hits:
            values_str = ", ".join(values_hits[:3])
            details.append(f"Values: {values_str}")
        
        # Policy alignment
        policy_hits = brain_ctx.get("policy_hits", [])
        if policy_hits and isinstance(policy_hits, list):
            policy_names = [p.get("name", "") for p in policy_hits[:2] if isinstance(p, dict) and p.get("name")]
            if policy_names:
                details.append(f"Policies: {', '.join(policy_names)}")
        
        if details:
            parts.append(" | ".join(details))
    elif tier:
        # Fallback if no brain context
        parts.append(f"Tier: {tier}")
    
    # Combine all parts
    return " • ".join(parts) if parts else "Evidence uploaded"


def _guess_kpa_from_text(text: str) -> str:
    """Simple heuristic to guess a human-friendly KPA label from free text."""
    t = (text or "").lower()
    if any(w in t for w in ["lecture", "tutorial", "assessment", "curriculum", "student", "teaching"]):
        return "Teaching & Learning"
    if any(w in t for w in ["publication", "journal", "conference", "research", "study", "manuscript"]):
        return "Research"
    if any(w in t for w in ["community", "engagement", "outreach", "service"]):
        return "Community Engagement"
    if any(w in t for w in ["lead", "chair", "management", "committee"]):
        return "Leadership & Management"
    if any(w in t for w in ["innovation", "impact", "project"]):
        return "Innovation & Impact"
    return "Teaching & Learning"


def _retry_ollama_and_update(
    evidence_id: str,
    filename: str,
    file_text: str,
    user_explanation: str,
    staff_id: str,
    year: int,
    month_bucket: str,
    initial_delay: int = 10,
    max_retries: int = 6,
):
    """Background retry loop that attempts to call Ollama and update evidence meta when available."""
    import time
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from progress_store import ProgressStore

    store = ProgressStore()
    delay = initial_delay
    for attempt in range(1, max_retries + 1):
        try:
            print(f"[OLLAMA RETRY] Attempt {attempt} for {evidence_id} (waiting {delay}s before call)")
            time.sleep(delay)

            prompt = f"""Provide a JSON classification for this evidence file.
Include fields: kpa (human-friendly), task, tier, impact_summary, confidence (0.0-1.0).

USER_EXPLANATION: {user_explanation or ''}
FILENAME: {filename}
CONTENT_PREVIEW: {file_text[:2000]}

Return only valid JSON."""

            ai_result = None
            try:
                ai_result = classify_with_ollama_raw(prompt)
            except Exception as e:
                print(f"[OLLAMA RETRY] call failed on attempt {attempt}: {e}")
                ai_result = None

            # If we got a meaningful structured result (not just a fallback), update DB and stop
            if ai_result and isinstance(ai_result, dict) and not ai_result.get("fallback"):
                try:
                    # Build enhanced impact summary combining user + ai + brain
                    # Fetch current evidence to obtain brain context
                    ev = store.get_evidence(evidence_id)
                    brain_ctx = {}
                    meta = {}
                    if ev:
                        try:
                            meta = json.loads(ev["meta_json"] or "{}")
                        except Exception:
                            meta = {}
                        brain_ctx = meta.get("brain", {}) or {}

                    enhanced = _build_enhanced_impact_summary(
                        user_description=user_explanation or "",
                        ai_summary=ai_result.get("impact_summary", ""),
                        brain_ctx=brain_ctx,
                        filename=filename,
                        tier=ai_result.get("tier", "")
                    )

                    ai_result["impact_summary"] = enhanced

                    # Persist updated ollama meta into evidence (merge via insert_evidence)
                    store.insert_evidence(
                        evidence_id=evidence_id,
                        sha1=meta.get("sha1", ""),
                        staff_id=staff_id,
                        year=int(year),
                        month_bucket=month_bucket,
                        kpa_code=meta.get("kpa_code", ""),
                        rating=meta.get("rating", ""),
                        tier=meta.get("tier", ""),
                        file_path=meta.get("file_path", ""),
                        meta={
                            **meta,
                            "ollama": ai_result,
                            "impact_summary": enhanced,
                        },
                    )
                    print(f"[OLLAMA RETRY] Updated evidence {evidence_id} with live Ollama result on attempt {attempt}")
                    return
                except Exception as e:
                    print(f"[OLLAMA RETRY] Failed to persist Ollama result: {e}")

            # Not successful — backoff and retry
            delay = min(delay * 2, 300)
        except Exception as e:
            print(f"[OLLAMA RETRY] Unexpected error during retry loop: {e}")
            delay = min(delay * 2, 300)

    print(f"[OLLAMA RETRY] Exhausted retries for {evidence_id}; leaving fallback ollama meta in place")


def classify_with_ollama_raw(prompt: str) -> Dict:
    """
    Raw Ollama classification with custom prompt.
    Returns parsed JSON classification result.
    """
    try:
        # Use centralized LLM wrapper (preferred) and allow longer timeouts in wrapper
        raw_text = None
        try:
            raw_text = query_ollama(prompt)
        except Exception as e:
            print(f"Central LLM call failed for raw classification: {e}")
            raw_text = ""

        if not raw_text:
            return {
                "kpa": _guess_kpa_from_text("") ,
                "task": "AI raw response",
                "tier": "Unknown",
                "impact_summary": "",
                "confidence": 0.6,
                "raw": "",
            }

        # Try to parse a variety of response shapes
        try:
            data = json.loads(raw_text)
        except Exception:
            # Not JSON from LLM; treat as raw text
            raw = raw_text.strip()
            return {
                "kpa": _guess_kpa_from_text(raw),
                "task": "AI raw response",
                "tier": "Unknown",
                "impact_summary": raw[:2000],
                "confidence": 0.6,
                "raw": raw,
            }

        # Common field locations
        ai_response = None
        if isinstance(data, dict):
            ai_response = data.get("response") or data.get("output") or data.get("text") or data.get("results")
        else:
            ai_response = data

        # If ai_response is already structured (dict), return or normalize
        if isinstance(ai_response, dict):
            return ai_response

        # If ai_response is a list, try to extract text from first element
        if isinstance(ai_response, list) and ai_response:
            first = ai_response[0]
            if isinstance(first, dict) and "content" in first:
                raw_text = first.get("content", "")
            else:
                raw_text = str(first)
        else:
            raw_text = str(ai_response or data.get("response", "") or "")

        # Attempt to parse JSON embedded in raw_text
        try:
            parsed = json.loads(raw_text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            raw = raw_text.strip()
            return {
                "kpa": _guess_kpa_from_text(raw),
                "task": (raw.split('\n', 1)[0])[:200],
                "tier": "Unknown",
                "impact_summary": raw[:2000],
                "confidence": 0.6,
                "raw": raw,
            }

    except Exception as e:
        print(f"Ollama raw classification error: {e}")
        raise


def classify_with_ollama(filename: str, content: str) -> Dict:
    """
    Use Ollama to classify evidence into KPAs.
    Uses prioritized keyword matching to avoid misclassification.
    """
    try:
        # Simple keyword-based classification as fallback
        content_lower = content.lower()
        filename_lower = filename.lower()
        combined = content_lower + " " + filename_lower
        
        # Keyword matching with priority order (most specific first)
        kpa = "Teaching & Learning"  # Default
        confidence = 0.5
        
        # Priority 1: Research (high signal words)
        if any(word in combined for word in ["publication", "journal article", "conference paper", "doi", "research project", "manuscript"]):
            kpa = "Research"
            confidence = 0.8
        # Priority 2: Community/Social (specific terms)
        elif any(word in combined for word in ["community engagement", "outreach program", "social responsibility", "public service"]):
            kpa = "Community Engagement"
            confidence = 0.75
        # Priority 3: Leadership (committee/admin)
        elif any(word in combined for word in ["committee meeting", "leadership role", "chair", "management position"]):
            kpa = "Leadership & Management"
            confidence = 0.75
        # Priority 4: Teaching (only if clear teaching context)
        elif any(word in combined for word in ["lecture", "tutorial", "student assessment", "curriculum", "teaching module"]):
            kpa = "Teaching & Learning"
            confidence = 0.7
        # Broader research terms (lower priority)
        elif any(word in combined for word in ["research", "study", "analysis"]):
            kpa = "Research"
            confidence = 0.6
        
        # Try Ollama with short timeout as enhancement
        try:
            prompt = f"""Classify this file into ONE of these categories:
1. Teaching & Learning
2. Research
3. Community Engagement
4. Innovation & Impact
5. Leadership & Management

Filename: {filename}
Content: {content[:300]}

Reply with ONLY the category name."""
            ai_response = ""
            try:
                ai_response = query_ollama(prompt) or ""
            except Exception as e:
                print(f"LLM classification error for {filename}: {e}")
                ai_response = ""

            ai_response = (ai_response or "").strip()
            if ai_response:
                # Check if response contains a valid KPA
                if "Teaching" in ai_response or "Learning" in ai_response:
                    kpa = "Teaching & Learning"
                    confidence = 0.85
                elif "Research" in ai_response:
                    kpa = "Research"
                    confidence = 0.85
                elif "Community" in ai_response:
                    kpa = "Community Engagement"
                    confidence = 0.85
                elif "Innovation" in ai_response or "Impact" in ai_response:
                    kpa = "Innovation & Impact"
                    confidence = 0.85
                elif "Leadership" in ai_response or "Management" in ai_response:
                    kpa = "Leadership & Management"
                    confidence = 0.85

        except Exception as ollama_error:
            print(f"LLM error for {filename}: {ollama_error}, using keyword classification")
        
        # Determine tier based on keywords
        tier = "Tier 2"
        if any(word in combined for word in ["lead", "chair", "coordinate", "manage"]):
            tier = "Tier 1"
        elif any(word in combined for word in ["support", "assist", "participate"]):
            tier = "Tier 3"
        
        return {
            "kpa": kpa,
            "task": f"Activity related to {kpa.lower()}",
            "tier": tier,
            "impact_summary": f"Evidence classified as {kpa} based on content analysis.",
            "confidence": confidence
        }
    
    except Exception as e:
        print(f"Classification error: {e}")
        return {
            "kpa": "Unclassified",
            "task": "Needs manual review",
            "tier": "N/A",
            "impact_summary": f"Classification failed: {str(e)[:100]}",
            "confidence": 0.3
        }

# ============================================================
# EVIDENCE STORE
# ============================================================

@app.route('/api/evidence', methods=['GET'])
def get_evidence():
    """
    Get stored evidence for a staff member
    """
    try:
        staff_id = request.args.get('staff_id')
        year = int(request.args.get('year') or datetime.now().year)
        month = request.args.get('month')
        kpa_code = request.args.get('kpa_code')

        if not staff_id:
            return jsonify({"error": "Missing staff_id"}), 400

        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from progress_store import ProgressStore

        store = ProgressStore()
        include_unmapped = str(request.args.get('include_unmapped') or '').lower() in ('1', 'true', 'yes')
        rows = store.list_evidence(
            staff_id=staff_id,
            year=year,
            month_bucket=month if month else None,
            kpa_code=kpa_code if kpa_code else None,
        )

        evidence = []
        seen_evidence_keys = set()
        for row in rows:
            evd = dict(row)
            try:
                meta = json.loads(evd.get("meta_json") or "{}")
            except Exception:
                meta = {}

            mapped_tasks = []
            try:
                for mapping in store.list_mappings_for_evidence(evd["evidence_id"]):
                    mapped_tasks.append({
                        "task_id": mapping["task_id"],
                        "title": mapping["title"],
                        "confidence": float(mapping["confidence"] or 0.0),
                        "mapped_by": mapping["mapped_by"],
                        "kpa_code": mapping["kpa_code"],
                    })
            except Exception:
                mapped_tasks = []

            source_meta = meta.get("outlook") or meta.get("efundi") or {}
            is_automated_source = isinstance(source_meta, dict) and bool(source_meta.get("source"))
            if not include_unmapped and not mapped_tasks and is_automated_source and not meta.get("user_enhanced"):
                continue

            brain_data = meta.get("brain") if isinstance(meta.get("brain"), dict) else {}
            file_path = evd.get("file_path") or ""
            display_key = (
                str(file_path or meta.get("filename") or evd.get("evidence_id") or "").lower(),
                str((mapped_tasks[0]["task_id"] if mapped_tasks else meta.get("target_task_id", "")) or "").lower(),
                str(meta.get("task") or "").lower(),
            )
            if display_key in seen_evidence_keys:
                continue
            seen_evidence_keys.add(display_key)
            feedback = _brain_feedback_fields(meta)
            evidence.append({
                "evidence_id": evd.get("evidence_id"),
                "staff_id": evd.get("staff_id"),
                "date": meta.get("date") or meta.get("timestamp") or "",
                "filename": meta.get("filename") or (Path(file_path).name if file_path else ""),
                "file": meta.get("filename") or (Path(file_path).name if file_path else ""),
                "file_path": file_path,
                "kpa": evd.get("kpa_code") or "",
                "kpa_code": evd.get("kpa_code") or "",
                "month": evd.get("month_bucket") or "",
                "month_bucket": evd.get("month_bucket") or "",
                "task": (mapped_tasks[0]["title"] if mapped_tasks else meta.get("task", "")),
                "task_id": (mapped_tasks[0]["task_id"] if mapped_tasks else meta.get("target_task_id", "")),
                "mapped_tasks": mapped_tasks,
                "mapped_count": len(mapped_tasks),
                "tier": evd.get("tier") or meta.get("tier") or "",
                "rating": brain_data.get("rating"),
                "rating_label": brain_data.get("rating_label", evd.get("rating") or ""),
                **feedback,
                "impact_summary": meta.get("impact_summary") or "",
                "confidence": (
                    float(mapped_tasks[0]["confidence"])
                    if mapped_tasks
                    else float(meta.get("confidence") or 0.0)
                ),
                "brain": brain_data,
                "meta": meta,
            })

        evidence.sort(
            key=lambda item: (
                int(item.get("mapped_count") or 0) <= 0,
                -float(item.get("confidence") or 0.0),
                str(item.get("date") or ""),
            )
        )
        include_all_evidence = str(request.args.get('include_all_evidence') or '').lower() in ('1', 'true', 'yes')
        if not include_all_evidence:
            capped = []
            per_task_counts = {}
            for item in evidence:
                task_key = item.get("task_id") or item.get("task") or item.get("evidence_id")
                count = per_task_counts.get(task_key, 0)
                if count >= 3:
                    continue
                per_task_counts[task_key] = count + 1
                capped.append(item)
            evidence = capped

        return jsonify({"evidence": evidence})
    
    except Exception as e:
        print(f"Evidence error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/evidence/resolve', methods=['POST'])
def resolve_evidence():
    """
    Resolve a classification dispute
    """
    try:
        data = request.json
        
        # Log the resolution
        print(f"Resolved: {data.get('file')} → {data.get('resolved_kpa')}")
        
        return jsonify({"status": "success"})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/evidence/enhance', methods=['POST'])
def enhance_evidence():
    """
    Enhance evidence confidence with user-provided description.
    Uses Ollama to reclassify evidence with semantic understanding.
    """
    try:
        data = request.json
        evidence_id = data.get('evidence_id')
        staff_id = data.get('staff_id')
        year = data.get('year')
        user_description = data.get('user_description', '').strip()
        target_task_id = data.get('target_task_id')  # Optional
        
        if not evidence_id or not staff_id or not year:
            return jsonify({"error": "Missing evidence_id, staff_id, or year"}), 400
        
        if not user_description:
            return jsonify({"error": "User description is required"}), 400
        
        # Load evidence from database
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from progress_store import ProgressStore
        from mapper import map_evidence_to_tasks
        import hashlib
        
        store = ProgressStore()
        
        # Get evidence metadata
        evidence_rows = store.list_evidence(staff_id=staff_id, year=int(year))
        evidence_item = None
        for row in evidence_rows:
            # Convert sqlite3.Row to dict
            row_dict = dict(row)
            if row_dict.get("evidence_id") == evidence_id:
                evidence_item = row_dict
                break
        
        if not evidence_item:
            return jsonify({"error": "Evidence not found"}), 404
        
        # Get original values
        old_kpa = evidence_item.get("kpa_code", "Unknown")
        # Parse metadata JSON if it's a string
        meta = evidence_item.get("meta", {})
        if isinstance(meta, str):
            import json
            try:
                meta = json.loads(meta)
            except:
                meta = {}
        old_confidence = float(meta.get("confidence", 0.0))
        file_path = evidence_item.get("file_path", "")
        filename = meta.get("filename", "")
        
        # Extract text from file
        file_text = ""
        try:
            from backend.vamp_master import extract_text_from_file
            file_text = extract_text_from_file(file_path) if Path(file_path).exists() else ""
        except Exception:
            file_text = filename  # Fallback
        
        # Classify with Ollama using user description
        print(f"[ENHANCE] Reclassifying {filename} with user description")
        
        enhanced_prompt = f"""You are classifying evidence for academic performance assessment.

USER CONTEXT (HIGHEST PRIORITY - TRUST THIS):
The staff member described this evidence as:
"{user_description}"

EVIDENCE FILE: {filename}
CONTENT PREVIEW (first 500 chars):
{file_text[:500] if file_text else 'N/A'}

Based primarily on the USER'S DESCRIPTION (which is highly trusted), classify this evidence:

1. KPA Classification (choose ONE):
   - KPA1: Teaching & Learning
   - KPA2: Occupational Health & Safety  
   - KPA3: Research & Innovation
   - KPA4: Academic Leadership & Administration
   - KPA5: Social Responsiveness & Engagement

2. Tier Level:
   - Transformational: Major impact, innovation
   - Developmental: Growth, improvement
   - Compliance: Meeting standards

3. Impact Summary: Brief description of the evidence's value (1-2 sentences)

4. Confidence: Based on user description clarity (0.85-0.95 typical for user-enhanced)

Return ONLY valid JSON:
{{
  "kpa": "KPA2",
  "task": "Brief task description",
  "tier": "Compliance",
  "impact_summary": "Based on user description, this evidence...",
  "confidence": 0.92
}}"""
        
        try:
            classification = classify_with_ollama_raw(enhanced_prompt)
        except Exception as e:
            print(f"[ENHANCE ERROR] Ollama classification failed: {e}")
            classification = {
                "kpa": old_kpa,
                "task": "Classification failed",
                "tier": "Unknown",
                "impact_summary": f"User description: {user_description[:100]}...",
                "confidence": min(0.85, old_confidence + 0.30)  # Boost anyway
            }
        
        # Map KPA name to code
        kpa_map = {
            "teaching": "KPA1", "teaching & learning": "KPA1",
            "ohs": "KPA2", "occupational health": "KPA2",
            "research": "KPA3", "innovation": "KPA3",
            "leadership": "KPA4", "administration": "KPA4",
            "social": "KPA5", "community": "KPA5"
        }
        new_kpa = classification.get("kpa", "KPA1")
        if not new_kpa.startswith("KPA"):
            kpa_lower = classification.get("kpa", "").lower()
            new_kpa = "KPA1"
            for key, code in kpa_map.items():
                if key in kpa_lower:
                    new_kpa = code
                    break
        
        new_confidence = float(classification.get("confidence", 0.90))
        new_impact = classification.get("impact_summary", user_description[:200])
        
        # Also run brain scorer if available for rating
        brain_ctx = None
        if BRAIN_SCORER_AVAILABLE and brain_score_evidence:
            try:
                brain_ctx = brain_score_evidence(
                    path=Path(file_path) if file_path else Path(filename),
                    full_text=f"{user_description}\n\n{file_text}",  # Include user description
                    kpa_hint_code=new_kpa
                )
                print(f"[ENHANCE] Brain rating: {brain_ctx.get('rating', 'N/A')}")
            except Exception as e:
                print(f"[ENHANCE] Brain scorer failed: {e}")
        
        # Create enhanced impact summary combining all sources
        enhanced_impact = _build_enhanced_impact_summary(
            user_description=user_description,
            ai_summary=new_impact,
            brain_ctx=brain_ctx,
            filename=filename,
            tier=classification.get("tier", "")
        )
        new_impact = enhanced_impact
        
        # Update evidence in database
        year = int(evidence_item.get("year", 2025))
        month_bucket = evidence_item.get("month_bucket", "")
        sha1 = evidence_item.get("sha1", hashlib.sha1(file_text.encode(errors="ignore")).hexdigest())
        
        updated_meta = evidence_item.get("meta", {})
        updated_meta.update({
            "user_description": user_description,
            "user_enhanced": True,
            "enhancement_date": datetime.utcnow().isoformat() + "Z",
            "original_confidence": old_confidence,
            "enhanced_confidence": new_confidence,
            "impact_summary": new_impact,
            "confidence": new_confidence,
        })
        
        store.insert_evidence(
            evidence_id=evidence_id,
            sha1=sha1,
            staff_id=staff_id,
            year=year,
            month_bucket=month_bucket,
            kpa_code=new_kpa,
            rating=(brain_ctx.get("rating_label") if brain_ctx else classification.get("tier")),
            tier=(brain_ctx.get("tier_label") if brain_ctx else classification.get("tier")),
            file_path=file_path,
            meta=updated_meta
        )
        
        # Clear old mappings and create new ones
        # (upsert will handle this in progress_store)
        month_num = int(month_bucket.split('-')[1]) if '-' in month_bucket else 1
        
        mapped_tasks = map_evidence_to_tasks(
            store,
            evidence_id=evidence_id,
            staff_id=staff_id,
            year=year,
            month_bucket=month_bucket,
            kpa_code=new_kpa,
            meta={
                "filename": filename,
                "impact_summary": new_impact,
                "evidence_type": classification.get("task", "")
            },
            mapped_by="user_enhanced:v1"
        )
        
        print(f"[ENHANCE] Success: {old_kpa} → {new_kpa}, conf {old_confidence:.2f} → {new_confidence:.2f}")
        
        return jsonify({
            "success": True,
            "evidence_id": evidence_id,
            "old_confidence": old_confidence,
            "new_confidence": new_confidence,
            "old_kpa": old_kpa,
            "new_kpa": new_kpa,
            "reclassified": (old_kpa != new_kpa),
            "old_mapped_count": 0,  # We cleared mappings
            "new_mapped_count": len(mapped_tasks),
            "rating": brain_ctx.get("rating") if brain_ctx else None,
            "message": "Evidence enhanced with user context"
        })
        
    except Exception as e:
        print(f"[ENHANCE ERROR] {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e), "success": False}), 500


@app.route('/api/evidence/kpa-scores', methods=['GET'])
def get_kpa_scores():
    """
    Calculate average rating scores per KPA for a given staff member and month.
    Returns scores on 0-5 scale from brain scorer ratings.
    """
    try:
        staff_id = request.args.get('staff_id')
        month = request.args.get('month')  # e.g., "2025-02" or "all"
        year = int(request.args.get('year') or (month.split('-')[0] if month and '-' in month else datetime.now().year))
        include_unmapped = str(request.args.get('include_unmapped') or '').lower() in ('1', 'true', 'yes')
        
        if not staff_id:
            return jsonify({"error": "Missing staff_id"}), 400
        
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from progress_store import ProgressStore
        
        store = ProgressStore()
        
        con = store._connect()
        try:
            where_month = ""
            args = [staff_id, year]
            if month and month != 'all':
                where_month = " AND e.month_bucket LIKE ?"
                args.append(f"{month}%")
            linked_rows = con.execute(
                f"""
                SELECT DISTINCT e.evidence_id, t.kpa_code AS mapped_kpa, e.meta_json
                FROM evidence e
                JOIN evidence_task et ON e.evidence_id = et.evidence_id
                JOIN tasks t ON t.task_id = et.task_id
                WHERE e.staff_id = ? AND e.year = ?{where_month}
                """,
                args,
            ).fetchall()

            evidence_rows = [
                {"evidence_id": r["evidence_id"], "kpa_code": r["mapped_kpa"], "meta_json": r["meta_json"]}
                for r in linked_rows
            ]

            if include_unmapped:
                unmapped_rows = con.execute(
                    f"""
                    SELECT e.evidence_id, e.kpa_code, e.meta_json
                    FROM evidence e
                    LEFT JOIN evidence_task et ON e.evidence_id = et.evidence_id
                    WHERE e.staff_id = ? AND e.year = ?{where_month}
                    GROUP BY e.evidence_id
                    HAVING COUNT(et.task_id) = 0
                    """,
                    args,
                ).fetchall()
                evidence_rows.extend([dict(r) for r in unmapped_rows])
        finally:
            con.close()
        
        # Group by KPA and calculate averages
        kpa_scores = {}
        kpa_counts = {}
        kpa_feedback = {}
        kpa_route_confidence = {}
        
        for row in evidence_rows:
            row_d = dict(row)
            kpa_code = row_d.get("kpa_code", "")
            if not kpa_code:
                continue
            
            # Try to get rating from brain scorer results
            rating = None
            try:
                meta = json.loads(row_d.get("meta_json") or "{}")
            except Exception:
                meta = {}
            brain_data = meta.get("brain", {})
            
            if isinstance(brain_data, dict):
                rating = brain_data.get("rating")
            
            # Fallback: try to extract from meta directly
            if rating is None:
                rating = meta.get("rating")
            
            if rating is not None:
                try:
                    rating = float(rating)
                    if 0 <= rating <= 5:
                        if kpa_code not in kpa_scores:
                            kpa_scores[kpa_code] = 0.0
                            kpa_counts[kpa_code] = 0
                            kpa_feedback[kpa_code] = {
                                "assessment_summaries": [],
                                "evidence_strengths": [],
                                "review_flags": [],
                                "recommended_actions": [],
                                "sample_evidence_ids": [],
                            }
                            kpa_route_confidence[kpa_code] = []
                        kpa_scores[kpa_code] += rating
                        kpa_counts[kpa_code] += 1

                        feedback = _brain_feedback_fields(meta)
                        bucket = kpa_feedback[kpa_code]
                        if feedback["assessment_summary"] and len(bucket["assessment_summaries"]) < 5:
                            bucket["assessment_summaries"].append(feedback["assessment_summary"])
                        if row_d.get("evidence_id") and len(bucket["sample_evidence_ids"]) < 8:
                            bucket["sample_evidence_ids"].append(row_d["evidence_id"])
                        for source_key in ("evidence_strengths", "review_flags", "recommended_actions"):
                            for item in feedback.get(source_key) or []:
                                if item and item not in bucket[source_key] and len(bucket[source_key]) < 8:
                                    bucket[source_key].append(item)
                        try:
                            if feedback["route_confidence"] is not None:
                                kpa_route_confidence[kpa_code].append(float(feedback["route_confidence"]))
                        except (TypeError, ValueError):
                            pass
                except (ValueError, TypeError):
                    pass
        
        # Calculate averages
        averages = {}
        for kpa_code in kpa_scores:
            if kpa_counts[kpa_code] > 0:
                averages[kpa_code] = round(kpa_scores[kpa_code] / kpa_counts[kpa_code], 2)
                confidences = kpa_route_confidence.get(kpa_code) or []
                if confidences:
                    kpa_feedback[kpa_code]["average_route_confidence"] = round(sum(confidences) / len(confidences), 2)
                else:
                    kpa_feedback[kpa_code]["average_route_confidence"] = None
        
        # Add KPA names
        kpa_names = {
            "KPA1": "Teaching & Learning",
            "KPA2": "Occupational Health & Safety",
            "KPA3": "Research & Innovation",
            "KPA4": "Academic Leadership",
            "KPA5": "Social Responsiveness"
        }
        
        result = {
            "ok": True,
            "staff_id": staff_id,
            "year": year,
            "month": month,
            "source": "linked_evidence_task",
            "include_unmapped": include_unmapped,
            "scores": averages,
            "counts": kpa_counts,
            "feedback": kpa_feedback,
            "kpa_names": kpa_names
        }
        
        print(f"[KPA SCORES] {staff_id} {month}: {averages}")
        
        return jsonify(result)
        
    except Exception as e:
        print(f"[KPA SCORES ERROR] {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e), "ok": False}), 500


# ============================================================
# AI GUIDANCE
# ============================================================

@app.route('/api/vamp/ask', methods=['POST'])
def ask_vamp():
    """
    Ask VAMP for AI guidance
    """
    try:
        data = request.json
        question = data.get('question')
        context = data.get('context', {})
        
        if not question:
            return jsonify({"error": "No question provided"}), 400
        
        # Short-greeting shortcut: avoid calling LLM for simple greetings
        q_lc = (question or "").strip().lower()
        short_greetings = {"hi", "hello", "hey", "hiya", "hi vamp", "hello vamp", "hey vamp", "hi eagi", "hello eagi", "hey eagi"}
        name = context.get('name') or context.get('staff_name') or 'there'
        if q_lc in short_greetings or (len(q_lc.split()) <= 2 and any(g in q_lc for g in short_greetings)):
            return jsonify({"answer": f"Hi {name}, I'm VAMP. How can I help you today?"})

        # Query Ollama with VAMP persona instructions
        prompt = build_vamp_prompt(question, context)
        answer = query_ollama(prompt, context)
        
        return jsonify({"answer": answer})
    
    except Exception as e:
        print(f"Ask VAMP error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/ai/guidance', methods=['POST'])
def ai_guidance():
    """
    Get AI guidance for a specific task
    """
    try:
        data = request.json
        question = data.get('question')
        context = data.get('context', {})
        
        print("=" * 60)
        print("AI GUIDANCE REQUEST:")
        print(f"Question: {question}")
        print(f"Context received: {json.dumps(context, indent=2)}")
        
        task_info = context.get('task')
        # If task info isn't provided as an object, try to recover from alternative fields
        if not task_info:
            # Common alternate forms: task_id, id, taskId
            alt_id = context.get('task_id') or context.get('id') or context.get('taskId')
            if isinstance(context.get('task'), str) and context.get('task'):
                alt_id = context.get('task')
            if alt_id:
                task_info = {'id': alt_id}
                print(f"Recovered task id from context: {alt_id}")
            else:
                # Try to locate the task using staff_id, cycle_year and scan_month from the expectations file
                staff_id = context.get('staff_id')
                year = context.get('cycle_year')
                month = context.get('scan_month')
                if staff_id and year and month:
                    try:
                        expectations_file = CONTRACTS_FOLDER.parent / "staff_expectations" / f"expectations_{staff_id}_{year}.json"
                        if expectations_file.exists():
                            with open(expectations_file, 'r') as f:
                                expectations_data = json.load(f)
                            by_month = expectations_data.get('by_month', {})
                            # Try explicit month key first
                            month_key = month if month in by_month else None
                            if not month_key and isinstance(month, str) and '-' in month:
                                month_key = month
                            if month_key and month_key in by_month:
                                month_tasks = by_month.get(month_key) or by_month.get(month_key, {}).get('tasks') or []
                                for t in month_tasks:
                                    # match against various id fields
                                    tid = t.get('id') or t.get('task_id') or t.get('_canonicalId') or t.get('_baseId')
                                    if tid == context.get('task_id') or tid == context.get('id') or tid == context.get('task'):
                                        task_info = t
                                        print(f"Located task in expectations by month: {t.get('id')} - {t.get('title')}")
                                        break
                            # As a last resort, search all tasks for the id
                            if not task_info and 'tasks' in expectations_data:
                                for t in expectations_data.get('tasks', []):
                                    tid = t.get('task_id') or t.get('id')
                                    if tid == context.get('task_id') or tid == context.get('id') or tid == context.get('task'):
                                        task_info = t
                                        print(f"Located base task in expectations: {t.get('id')} - {t.get('title')}")
                                        break
                    except Exception as _e:
                        print(f"Error while attempting to recover task from expectations file: {_e}")

        # Ensure context.task is always present (empty dict if unresolved)
        if not task_info:
            # Try to recover minimal task id if present so templates/LLM have something
            alt_id = context.get('task_id') or context.get('id') or context.get('task') or None
            task_info = {'id': alt_id} if alt_id else {}
            print("⚠️ WARNING: No task information in context; proceeding with minimal context.")

        if task_info is None:
            task_info = {}

        # Place task_info back into context early so template/generator can use it
        try:
            context['task'] = task_info
        except Exception:
            pass

        if task_info:
            # Ensure we attach a _baseId when possible so template scope matching works
            try:
                if not task_info.get('_baseId'):
                    staff_id = context.get('staff_id')
                    year = context.get('cycle_year')
                    expectations_file = CONTRACTS_FOLDER.parent / "staff_expectations" / f"expectations_{staff_id}_{year}.json"

                    # Load expectations (prefer cached)
                    expectations_data = None
                    cached = expectations_cache.get((staff_id, year))
                    if cached and (cached.get('_id_map') or any((t.get('hashed_ids') for t in (cached.get('tasks') or [])))):
                        expectations_data = cached
                        if DEBUG:
                            print(f"Using cached expectations for {staff_id}/{year}")
                    elif expectations_file.exists():
                        try:
                            with open(expectations_file, 'r') as f:
                                expectations_data = json.load(f)
                            if DEBUG:
                                print(f"Found expectations file: {expectations_file}")
                                print(f"Expectations tasks count: {len(expectations_data.get('tasks') or [])}")
                        except Exception as _e:
                            print(f"Error reading expectations file: {_e}")
                    else:
                        expectations_data = None

                    if expectations_data:
                        logger.info(f"ENRICHMENT: expectations_data present. tasks_count={len(expectations_data.get('tasks') or [])}, has_id_map={('_id_map' in expectations_data)}")
                        
                        # Build _id_map if not present (for consistency with /api/expectations)
                        if '_id_map' not in expectations_data and TASK_MAP_AVAILABLE:
                            # First, ensure tasks have hashed_ids populated
                            for bt in expectations_data.get('tasks', []):
                                base_id = bt.get('task_id') or bt.get('id')
                                if not bt.get('hashed_ids') and base_id:
                                    bt['hashed_ids'] = {}
                                    # Generate for all months (01-12)
                                    for month in range(1, 13):
                                        try:
                                            hid = _hid(staff_id, str(year), base_id, f"{month:02d}")
                                            bt['hashed_ids'][str(month)] = hid
                                        except Exception as _e:
                                            pass
                            
                            id_map = {}
                            for bt in expectations_data.get('tasks', []):
                                base_id = bt.get('task_id') or bt.get('id')
                                hashed_ids = bt.get('hashed_ids') or {}
                                if isinstance(hashed_ids, dict):
                                    for mon, hid in hashed_ids.items():
                                        if hid:
                                            id_map[str(hid)] = base_id
                            expectations_data['_id_map'] = id_map
                            logger.info(f"Built _id_map with {len(id_map)} entries")
                        
                        # Fast path: use top-level id_map (hashed -> base) if available
                        try:
                            id_map = expectations_data.get('_id_map') or {}
                            if id_map and isinstance(id_map, dict):
                                # debug info (always show for diagnostics)
                                logger.debug(f"_id_map sample keys: {list(id_map.keys())[:10]}")
                                mapped = id_map.get(str(task_info.get('id')))
                                logger.debug(f"_id_map lookup for {task_info.get('id')}: {mapped}")
                                if mapped:
                                    task_info['_baseId'] = mapped
                                    logger.info(f"Resolved _baseId via _id_map: {mapped}")
                                    # Enrich task_info with base task fields for template selection
                                    try:
                                        base_tasks = expectations_data.get('tasks') or []
                                        for bt in base_tasks:
                                            if (bt.get('task_id') or bt.get('id')) == mapped:
                                                # Copy useful fields if missing
                                                for src, dst in [('title','title'), ('kpa_name','kpa'), ('kpa_code','kpa'), ('outputs','goal'), ('evidence_hints','evidence_hints'), ('evidence_required','evidence_required'), ('minimum_count','minimum_count')]:
                                                    if bt.get(src) is not None and not task_info.get(dst):
                                                        task_info[dst] = bt.get(src)
                                                if DEBUG:
                                                    print(f"Enriched task_info from base task {mapped}: title={task_info.get('title')}, kpa={task_info.get('kpa')}")
                                                # Always log a short summary so tests can observe behavior
                                                logger.info(f"ENRICHMENT: task_info after id_map resolution: id={task_info.get('id')}, _baseId={task_info.get('_baseId')}, title={task_info.get('title')}, kpa={task_info.get('kpa')}")
                                                break
                                    except Exception as _e:
                                        logger.error(f"Error enriching from base task after _id_map resolution: {_e}")
                                else:
                                    logger.debug(f"_id_map lookup miss for key: {task_info.get('id')}")
                        except Exception as _e:
                            logger.error(f"Error checking _id_map: {_e}")

                        # check by_month entries for a match
                        for mk, md in (expectations_data.get('by_month') or {}).items():
                            month_tasks = md.get('tasks') or []
                            # debug: show a sample task id for traceability
                            if month_tasks and DEBUG:
                                logger.debug(f"Month {mk} sample task id: {month_tasks[0].get('id')} (keys: {list(month_tasks[0].keys())[:6]})")
                            for t in month_tasks:
                                if t.get('id') == task_info.get('id') or t.get('_canonicalId') == task_info.get('id') or t.get('_baseId') == task_info.get('id'):
                                    # copy base id into task_info for matching
                                    if t.get('_baseId'):
                                        task_info['_baseId'] = t.get('_baseId')
                                        # copy useful fields from the month task
                                        for fld in ['title', 'kpa', 'kpa_code', 'minimum_count', 'stretch_count', 'evidence_hints']:
                                            if not task_info.get(fld) and t.get(fld) is not None:
                                                task_info[fld] = t.get(fld)
                                        if DEBUG:
                                            logger.debug(f"Located task in by_month and copied _baseId: {task_info.get('_baseId')}")
                                        break
                            if task_info.get('_baseId'):
                                break

                        # If still not found, scan base tasks' hashed_ids as a fallback
                        if not task_info.get('_baseId'):
                            logger.info(f"Scanning {len(expectations_data.get('tasks') or [])} base tasks for hashed_ids match...")
                            for bt in (expectations_data.get('tasks') or []):
                                hashed = bt.get('hashed_ids') or {}
                                # show a quick sample of this base task's hashed ids
                                if isinstance(hashed, dict):
                                    sample = list(hashed.items())[:3]
                                    logger.debug(f"Checking base {bt.get('id')}: sample hashed ids {sample}")
                                if isinstance(hashed, dict) and any(h == task_info.get('id') for h in hashed.values()):
                                    task_info['_baseId'] = bt.get('task_id') or bt.get('id')
                                    # shallow-merge useful fields to improve template selection
                                    for fld in ['title', 'kpa_name', 'kpa_code', 'outputs', 'evidence_hints', 'minimum_count', 'stretch_count']:
                                        if not task_info.get(fld) and bt.get(fld) is not None:
                                            task_info[fld] = bt.get(fld)
                                    logger.info(f"Matched hashed id to base task via hashed_ids: {task_info.get('_baseId')}")
                                    break

                        # As a robust fallback, try the on-disk expectations file directly
                        if not task_info.get('_baseId') and expectations_file.exists():
                            try:
                                with open(expectations_file, 'r') as ef:
                                    file_expect = json.load(ef)
                                for bt in (file_expect.get('tasks') or []):
                                    hashed = bt.get('hashed_ids') or {}
                                    if isinstance(hashed, dict) and any(h == task_info.get('id') for h in hashed.values()):
                                        task_info['_baseId'] = bt.get('task_id') or bt.get('id')
                                        for fld in ['title', 'kpa_name', 'kpa_code', 'outputs', 'evidence_hints', 'minimum_count', 'stretch_count']:
                                            if not task_info.get(fld) and bt.get(fld) is not None:
                                                task_info[fld] = bt.get(fld)
                                        if DEBUG:
                                            print(f"Matched hashed id to base task via on-disk file: {task_info.get('_baseId')}")
                                        break
                            except Exception as _e:
                                print(f"Error while scanning on-disk expectations for hashed ids: {_e}")

                        # Final fallback: compute _hid for base tasks and compare
                        if not task_info.get('_baseId') and TASK_MAP_AVAILABLE and _hid:
                            try:
                                search_tasks = expectations_data.get('tasks') or []
                                if not search_tasks and expectations_file.exists():
                                    with open(expectations_file, 'r') as ef:
                                        file_expect = json.load(ef)
                                    search_tasks = file_expect.get('tasks') or []

                                found_hid = False
                                for bt in (search_tasks or []):
                                    months = bt.get('months') or []
                                    for m in months:
                                        try:
                                            month_int = int(m)
                                            hid = _hid(staff_id, str(year), str(bt.get('id') or bt.get('task_id')), f"{month_int:02d}")
                                            if hid == task_info.get('id'):
                                                task_info['_baseId'] = bt.get('task_id') or bt.get('id')
                                                for fld in ['title', 'kpa_name', 'kpa_code', 'outputs', 'evidence_hints', 'minimum_count', 'stretch_count']:
                                                    if not task_info.get(fld) and bt.get(fld) is not None:
                                                        task_info[fld] = bt.get(fld)
                                                if DEBUG:
                                                    logger.info(f"Matched hashed id to base task by computing _hid: {task_info.get('_baseId')}")
                                                found_hid = True
                                                break
                                        except Exception:
                                            continue
                                    if found_hid:
                                        break
                            except Exception as _e:
                                print(f"Error while attempting to compute hashed ids for mapping: {_e}")

                        # If still not found, search base tasks directly
                        if not task_info.get('_baseId'):
                            for t in (expectations_data.get('tasks') or []):
                                # direct match against base id
                                if t.get('task_id') == task_info.get('id') or t.get('id') == task_info.get('id'):
                                    task_info['_baseId'] = t.get('task_id') or t.get('id')
                                    if DEBUG:
                                        print(f"Matched base id directly: {task_info.get('_baseId')}")
                                    break
                                # match against hashed ids stored on base tasks
                                hashed = t.get('hashed_ids') or {}
                                if isinstance(hashed, dict) and any(h == task_info.get('id') for h in hashed.values()):
                                    task_info['_baseId'] = t.get('task_id') or t.get('id')
                                    if DEBUG:
                                        print(f"Matched hashed id to base task: {task_info.get('_baseId')}")
                                    break
            except Exception as _e:
                print(f"Error while attempting to enrich task info: {_e}")

            # Build a concise task_summary if available so the LLM/generator has a full prompt
            try:
                if not task_info.get('task_summary'):
                    pieces = []
                    if task_info.get('kpa'):
                        pieces.append(f"{task_info.get('kpa')}")
                    if task_info.get('title'):
                        pieces.append(f"{task_info.get('title')}")
                    if task_info.get('what_to_do'):
                        pieces.append(f"What to do: {task_info.get('what_to_do')}")
                    if task_info.get('evidence_required'):
                        pieces.append(f"Evidence required: {task_info.get('evidence_required')}")
                    if pieces:
                        task_info['task_summary'] = "\n".join(pieces)
            except Exception:
                pass

            # Ensure enriched task info is placed back into the context so template/LLM renderers can access it
            try:
                context['task'] = task_info
            except Exception:
                pass

            print(f"Task ID: {task_info.get('id')}")
            if DEBUG:
                print(f"Task Title: {task_info.get('title')}")
                print(f"Task KPA: {task_info.get('kpa')}")
                print(f"Task _baseId: {task_info.get('_baseId')}")
        else:
            print("⚠️ WARNING: No task information in context!")
        print("=" * 60)
        
        # Try template-based guidance first (fast, deterministic)
        try:
            # Load and render template (single-call helper)
            try:
                from backend.guidance_renderer import get_rendered_template, generate_qualitative_guidance
                # Try auto-generated templates first, then static templates
                tmpl = None
                try:
                    tmpl = get_rendered_template(DATA_FOLDER / 'auto_guidance_templates.json', context, variant='short')
                except Exception:
                    tmpl = None
                if not tmpl:
                    tmpl = get_rendered_template(DATA_FOLDER / 'guidance_templates.json', context, variant='short')
                if tmpl and tmpl.get('text'):
                    return jsonify({"guidance": tmpl.get('text'), "source": "template", "template_id": tmpl.get('template_id')})

                # If no strict template match, generate a concise, personal guidance
                gen = generate_qualitative_guidance(context, variant='short_personal')
                if gen and gen.get('text'):
                    return jsonify({"guidance": gen.get('text'), "source": "generated", "template_id": gen.get('template_id')})
            except Exception as _e:
                print(f"Template/Generator error: {_e}")
        except Exception as _e:
            print(f"Template rendering error: {_e}")

        # Fallback: Query Ollama
        guidance = query_ollama(f"Provide guidance: {question}", context)
        
        return jsonify({"guidance": guidance, "source": "llm"})
    
    except Exception as e:
        print(f"❌ AI GUIDANCE ERROR: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

# ============================================================
# REPORT GENERATION
# ============================================================

@app.route('/api/report/generate', methods=['GET'])
def generate_report():
    """
    Generate Performance Agreement report matching Excel format with actual weights and KPIs
    """
    try:
        staff_id = request.args.get('staff_id')
        year = request.args.get('year')
        
        if not staff_id or not year:
            return jsonify({"error": "Missing staff_id or year"}), 400
        
        # Try expectations file first (has richer data with weights)
        expectations_file = Path("backend/data/staff_expectations") / f"expectations_{staff_id}_{year}.json"
        contract_file = CONTRACTS_FOLDER / f"contract_{staff_id}_{year}.json"
        
        contract_data = None
        if expectations_file.exists():
            with open(expectations_file, 'r') as f:
                expectations_data = json.load(f)
            # Build contract_data from expectations for PA generator
            contract_data = {
                "kpa_summary": expectations_data.get("kpa_summary", {}),
                "tasks": expectations_data.get("tasks", [])
            }
        elif contract_file.exists():
            with open(contract_file, 'r') as f:
                contract_data = json.load(f)
        else:
            return jsonify({"error": "No contract or expectations data found"}), 404
        
        # Generate PA report
        from backend.contracts.pa_report_generator import generate_pa_report, export_pa_to_excel
        
        pa_data = generate_pa_report(contract_data, staff_id, int(year))
        
        # Optionally export to Excel
        export_excel = request.args.get('export', 'false').lower() == 'true'
        if export_excel:
            output_dir = Path("backend/data/performance_agreements")
            output_dir.mkdir(parents=True, exist_ok=True)
            output_file = output_dir / f"PA_{staff_id}_{year}_web.xlsx"
            export_pa_to_excel(pa_data, output_file)
            pa_data["excel_path"] = str(output_file)
        
        return jsonify(pa_data)
    
    except Exception as e:
        print(f"PA generation error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

# ============================================================
# ELEVENLABS TTS API
# ============================================================

try:
    from backend.llm.elevenlabs_tts import text_to_speech, sanitize_for_speech, get_tts_client
    ELEVENLABS_AVAILABLE = True
    print("✓ ElevenLabs TTS loaded successfully")
except ImportError as e:
    print(f"Warning: ElevenLabs TTS not available: {e}")
    ELEVENLABS_AVAILABLE = False
    text_to_speech = None
    sanitize_for_speech = None
    get_tts_client = None

try:
    from backend.llm import voice_cloner as local_voice_cloner
    VOICE_CLONER_AVAILABLE = bool(getattr(local_voice_cloner, "OPENVOICE_AVAILABLE", False))
    get_voice_cloner = local_voice_cloner.get_voice_cloner
    local_text_to_speech = local_voice_cloner.text_to_speech
    if VOICE_CLONER_AVAILABLE:
        print("✓ OpenVoice local voice cloning loaded successfully")
    else:
        print(f"Warning: OpenVoice local voice cloning not available: {getattr(local_voice_cloner, 'OPENVOICE_IMPORT_ERROR', 'unknown import error')}")
except Exception as e:
    print(f"Warning: OpenVoice local voice cloning not available: {e}")
    VOICE_CLONER_AVAILABLE = False
    get_voice_cloner = None
    local_text_to_speech = None

def synthesize_vamp_voice(text: str):
    """Prefer local trained OpenVoice; fall back to ElevenLabs when needed."""
    clean_text = sanitize_for_speech(text) if sanitize_for_speech else text
    sidecar_python = Path(".venv-openvoice/bin/python")
    sidecar_script = Path("scripts/synthesize_kaimil_sidecar.py")
    sidecar_embedding = Path("cache/voice/Conversational kAImil_embedding.pt")
    sidecar_configured = sidecar_python.exists() and sidecar_script.exists() and sidecar_embedding.exists()
    if sidecar_configured:
        try:
            proc = subprocess.run(
                [
                    str(sidecar_python),
                    str(sidecar_script),
                    "--text",
                    clean_text,
                    "--voice-name",
                    "Conversational kAImil",
                ],
                cwd=str(Path(__file__).resolve().parent),
                env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parent)},
                text=True,
                capture_output=True,
                timeout=240,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                payload = json.loads(proc.stdout.strip().splitlines()[-1])
                audio_path = Path(payload.get("path", ""))
                if payload.get("success") and audio_path.exists():
                    return audio_path, "openvoice_sidecar"
            else:
                print(f"OpenVoice sidecar failed: {proc.stderr[-1200:]}")
        except Exception as e:
            print(f"OpenVoice sidecar synthesis failed; falling back if possible: {e}")
        # Avoid mixing in the old EAGIBOT/ElevenLabs voice when the local VAMP
        # voice is configured. A failed local generation should be silent, not
        # a different character speaking first.
        return None, "openvoice_sidecar"
    if VOICE_CLONER_AVAILABLE and local_text_to_speech:
        try:
            audio_path = local_text_to_speech(clean_text)
            if audio_path:
                return audio_path, "openvoice"
        except Exception as e:
            print(f"OpenVoice synthesis failed; falling back if possible: {e}")
    if ELEVENLABS_AVAILABLE and text_to_speech:
        try:
            audio_path = text_to_speech(clean_text)
            if audio_path:
                return audio_path, "elevenlabs"
        except Exception as e:
            print(f"ElevenLabs synthesis failed: {e}")
    return None, "none"

@app.route('/api/voice/status', methods=['GET'])
def voice_status():
    """Get local/ElevenLabs TTS status."""
    try:
        sidecar_python = Path(".venv-openvoice/bin/python")
        sidecar_script = Path("scripts/synthesize_kaimil_sidecar.py")
        sidecar_embedding = Path("cache/voice/Conversational kAImil_embedding.pt")
        if sidecar_python.exists() and sidecar_script.exists() and sidecar_embedding.exists():
            return jsonify({
                "available": True,
                "engine": "openvoice_sidecar",
                "openvoice_available": True,
                "is_trained": True,
                "voice_name": "Conversational kAImil",
                "embedding_path": str(sidecar_embedding),
                "training_files_available": len(list(Path("data/voice_samples").glob("kaimil_*.wav"))),
                "sidecar_python": str(sidecar_python),
            })

        local_status = None
        if VOICE_CLONER_AVAILABLE and get_voice_cloner:
            try:
                local_status = get_voice_cloner().status()
            except Exception as e:
                local_status = {"error": str(e), "openvoice_available": False}

        if local_status:
            payload = {
                "available": True,
                "engine": "openvoice",
                **local_status,
            }
            if ELEVENLABS_AVAILABLE and get_tts_client:
                try:
                    client = get_tts_client()
                    voice_info = client.get_voice_info()
                    payload["fallback_engine"] = "elevenlabs"
                    payload["fallback_voice_id"] = client.VOICE_ID
                    payload["fallback_voice_name"] = voice_info.get("name") if voice_info else getattr(client, "VOICE_NAME_HINT", "Conversational kAImil")
                    payload["quota"] = client.check_quota()
                except Exception:
                    pass
            return jsonify(payload)

        if not ELEVENLABS_AVAILABLE:
            return jsonify({
                "available": False,
                "error": "No voice engine available. Install OpenVoice for local training or configure ElevenLabs."
            })
        
        client = get_tts_client()
        quota = client.check_quota()
        voice_info = client.get_voice_info()
        
        return jsonify({
            "available": True,
            "engine": "elevenlabs",
            "voice_id": client.VOICE_ID,
            "configured_voice_name": getattr(client, "VOICE_NAME_HINT", "Conversational kAImil"),
            "voice_name": voice_info.get("name") if voice_info else "Unknown",
            "quota": quota
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/voice/train', methods=['POST'])
def voice_train():
    """Train voice model with uploaded samples"""
    try:
        if not VOICE_CLONER_AVAILABLE:
            return jsonify({"error": "Voice cloner not available"}), 503
        
        data = request.json
        voice_name = data.get('voice_name', 'Conversational kAImil')
        
        # Get uploaded files from training directory
        cloner = get_voice_cloner()
        training_files = cloner.get_training_files()
        
        if not training_files:
            return jsonify({
                "error": "No training files found. Please upload voice samples first."
            }), 400
        
        # Train the voice
        result = cloner.train_voice(training_files, voice_name)
        return jsonify(result)
    
    except Exception as e:
        print(f"Voice training error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/voice/upload', methods=['POST'])
def voice_upload():
    """Upload voice training samples"""
    try:
        if not VOICE_CLONER_AVAILABLE:
            return jsonify({"error": "Voice cloner not available"}), 503
        
        if 'file' not in request.files:
            return jsonify({"error": "No file uploaded"}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "Empty filename"}), 400
        
        # Get training directory
        cloner = get_voice_cloner()
        filename = secure_filename(file.filename)
        filepath = cloner.training_dir / filename
        
        # Save the file
        file.save(str(filepath))
        
        return jsonify({
            "success": True,
            "filename": filename,
            "path": str(filepath)
        })
    
    except Exception as e:
        print(f"Voice upload error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/voice/synthesize', methods=['POST'])
def voice_synthesize():
    """Convert text to speech using local OpenVoice when trained, otherwise ElevenLabs."""
    try:
        data = request.json
        text = data.get('text')
        
        if not text:
            return jsonify({"error": "No text provided"}), 400
        
        audio_path, engine = synthesize_vamp_voice(text)
        
        if audio_path is None:
            return jsonify({"error": "Speech generation failed"}), 500
        
        # Return audio file info
        return jsonify({
            "success": True,
            "audio_url": f"/api/voice/audio/{audio_path.name}",
            "filename": audio_path.name,
            "engine": engine
        })
    
    except Exception as e:
        print(f"Voice synthesis error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/voice/audio/<filename>')
def voice_audio(filename):
    """Serve generated audio files from local OpenVoice or ElevenLabs caches."""
    try:
        search_dirs = []
        if VOICE_CLONER_AVAILABLE and get_voice_cloner:
            try:
                search_dirs.append(get_voice_cloner().cache_dir)
            except Exception:
                pass
        sidecar_cache = Path("cache/voice")
        if sidecar_cache.exists():
            search_dirs.append(sidecar_cache)
        if ELEVENLABS_AVAILABLE and get_tts_client:
            search_dirs.append(get_tts_client().cache_dir)

        for cache_dir in search_dirs:
            audio_path = Path(cache_dir) / filename
            if audio_path.exists():
                mimetype = 'audio/wav' if audio_path.suffix.lower() == '.wav' else 'audio/mpeg'
                return send_from_directory(str(cache_dir), filename, mimetype=mimetype)

        return jsonify({"error": "Audio file not found"}), 404
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/vamp/ask-voice', methods=['POST'])
def ask_vamp_voice():
    """
    Ask VAMP for AI guidance with voice response.
    """
    try:
        data = request.json
        question = data.get('question')
        context = data.get('context', {})
        
        if not question:
            return jsonify({"error": "No question provided"}), 400
        
        # Short-greeting shortcut: avoid calling LLM for simple greetings
        q_lc = (question or "").strip().lower()
        short_greetings = {"hi", "hello", "hey", "hiya", "hi vamp", "hello vamp", "hey vamp", "hi eagi", "hello eagi", "hey eagi"}
        name = context.get('name') or context.get('staff_name') or 'there'
        if q_lc in short_greetings or (len(q_lc.split()) <= 2 and any(g in q_lc for g in short_greetings)):
            clean_answer = f"Hi {name}, I'm VAMP. How can I help you today?"
            audio_path, engine = synthesize_vamp_voice(clean_answer)
            audio_url = f"/api/voice/audio/{audio_path.name}" if audio_path else None
            return jsonify({
                "answer": clean_answer,
                "audio_url": audio_url,
                "has_voice": audio_url is not None,
                "voice_engine": engine
            })

        # Query Ollama for text response with VAMP persona instructions
        prompt = build_vamp_prompt(question, context)
        answer = query_ollama(prompt, context)
        
        clean_answer = sanitize_for_speech(answer) if sanitize_for_speech else answer
        audio_path, engine = synthesize_vamp_voice(clean_answer)
        audio_url = f"/api/voice/audio/{audio_path.name}" if audio_path else None
        
        return jsonify({
            "answer": clean_answer,
            "audio_url": audio_url,
            "has_voice": audio_url is not None,
            "voice_engine": engine
        })
    
    except Exception as e:
        print(f"Ask VAMP voice error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/debug/status', methods=['GET'])
def debug_status():
    """Lightweight diagnostics endpoint to assist debugging (contracts, Ollama, ElevenLabs)."""
    try:
        contracts = []
        expectations = []
        try:
            if CONTRACTS_FOLDER.exists():
                contracts = [p.name for p in CONTRACTS_FOLDER.iterdir() if p.is_file()]
        except Exception:
            contracts = []

        staff_expect_folder = CONTRACTS_FOLDER.parent / 'staff_expectations'
        try:
            if staff_expect_folder.exists():
                expectations = [p.name for p in staff_expect_folder.iterdir() if p.is_file()]
        except Exception:
            expectations = []

        # Check LLM reachability via centralized wrapper (short ping)
        ollama_ok = False
        ollama_error = None
        try:
            ping_resp = query_ollama("Ping")
            ollama_ok = bool(ping_resp and str(ping_resp).strip())
        except Exception as e:
            ollama_error = str(e)

        return jsonify({
            "ok": True,
            "contracts": contracts,
            "expectations_files": expectations,
            "ollama_ok": ollama_ok,
            "ollama_error": ollama_error,
            "elevenlabs_available": ELEVENLABS_AVAILABLE
        })
    except Exception as e:
        print(f"Debug status error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

# ============================================================
# SERVER-SENT EVENTS
# ============================================================

@app.route('/api/scan/events')
def scan_events():
    """
    Server-Sent Events for real-time scan updates
    """
    def event_stream():
        client_id = id(request)
        event_clients.append(client_id)
        
        try:
            while True:
                # Keep connection alive
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
                time.sleep(30)
        except GeneratorExit:
            if client_id in event_clients:
                event_clients.remove(client_id)
    
    return Response(event_stream(), mimetype="text/event-stream")

def send_event(data: Dict):
    """Send event to all connected clients"""
    # In production, use a proper pub/sub system
    print(f"Event: {data}")

# ============================================================
# MAIN
# ============================================================

def sync_expectations_to_db():
    """
    Read all files in backend/data/staff_expectations/ and ensure the
    ProgressStore contains the canonical per-month tasks derived from
    each expectations JSON. This makes the DB deterministic on startup.
    """
    try:
        from progress_store import ProgressStore
        from mapper import ensure_tasks
    except Exception as e:
        print(f"Startup sync: could not import ProgressStore/ensure_tasks: {e}")
        return

    expect_dir = CONTRACTS_FOLDER.parent / "staff_expectations"
    if not expect_dir.exists():
        return

    for p in sorted(expect_dir.glob('expectations_*.json')):
        try:
            with open(p, 'r', encoding='utf-8') as fh:
                data = json.load(fh)

            staff_id = data.get('staff_id') or None
            year = data.get('year') or None
            # Fallback to filename parse if missing
            if (not staff_id or not year) and p.stem:
                parts = p.stem.split('_')
                try:
                    # expectations_{staff}_{year}
                    staff_id = staff_id or parts[1]
                    year = year or int(parts[2])
                except Exception:
                    pass

            if not staff_id or not year:
                print(f"Startup sync: skipping {p} (no staff_id/year)")
                continue

            print(f"Startup sync: ensuring tasks for {staff_id}/{year} from {p.name}")
            store = ProgressStore()
            try:
                ensure_tasks(store, staff_id=str(staff_id), year=int(year), expectations=data)
            except Exception as e:
                print(f"Startup sync: ensure_tasks failed for {staff_id}/{year}: {e}")
        except Exception as e:
            print(f"Startup sync: failed to process {p}: {e}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Run the VAMP web UI/API server.")
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port to bind the web server to (default: {DEFAULT_PORT}).",
    )
    args = parser.parse_args()
    PORT = args.port

    print("=" * 60)
    print("VAMP Web Server Starting")
    print("=" * 60)
    print(f"AI Provider: Groq (Cloud)")
    print(f"AI Model: {GROQ_MODEL}")
    print(f"API Key: {'Configured ✓' if GROQ_API_KEY else 'NOT SET - Get free key at https://console.groq.com'}")
    print(f"Upload Folder: {UPLOAD_FOLDER}")
    print(f"Data Folder: {DATA_FOLDER}")
    print("=" * 60)
    print(f"\nServer running at: http://localhost:{PORT}")
    print(f"Open http://localhost:{PORT} in your browser")
    print("\nPress Ctrl+C to stop")
    print("=" * 60)
    
    # Run a startup sync to make sure the DB matches on-disk expectations
    try:
        sync_expectations_to_db()
    except Exception as _e:
        print(f"Startup sync error: {_e}")

    # Run without the debug auto-reloader for stable testing sessions.
    # Keep threaded=True for concurrency; explicit `use_reloader=False` prevents restarts.
    app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False, threaded=True)
