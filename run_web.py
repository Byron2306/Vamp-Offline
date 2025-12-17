#!/usr/bin/env python3
"""
VAMP Web Server - Comprehensive API backend with Ollama integration
"""

import os
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any
from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS
from werkzeug.utils import secure_filename
import requests

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
    EXPECTATION_ENGINE_AVAILABLE = False
    parse_task_agreement = None
    build_expectations_from_ta = None

try:
    from backend.nwu_brain_scorer import brain_score_evidence
    BRAIN_SCORER_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Could not import brain_score_evidence: {e}")
    BRAIN_SCORER_AVAILABLE = False
    brain_score_evidence = None

print(f"Expectation engine available: {EXPECTATION_ENGINE_AVAILABLE}")

# Flask setup
app = Flask(__name__, static_folder='.')
CORS(app)

# Configuration
UPLOAD_FOLDER = Path("./uploads")
DATA_FOLDER = Path("./backend/data")
CONTRACTS_FOLDER = DATA_FOLDER / "contracts"
EVIDENCE_FOLDER = DATA_FOLDER / "evidence"
UPLOAD_FOLDER.mkdir(exist_ok=True)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:1b")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "180"))

# Global state
profiles = {}
expectations_cache = {}
evidence_store = None
event_clients = []

# ============================================================
# OLLAMA INTEGRATION
# ============================================================

def query_ollama(prompt: str, context: Dict = None) -> str:
    """
    Query Ollama LLM for AI responses
    """
    try:
        # Build enhanced prompt with context
        if context:
            enhanced_prompt = f"""You are VAMP (Virtual Academic Management Partner), an AI assistant for academic performance management at NWU.

Context:
- Staff ID: {context.get('staff_id', 'Unknown')}
- Cycle Year: {context.get('cycle_year', 'Unknown')}
- Current Stage: {context.get('stage', 'Unknown')}
- Current Tab: {context.get('current_tab', 'Unknown')}
- Expectations Loaded: {context.get('expectations_count', 0)}
- Scan Results: {context.get('scan_results_count', 0)}

User Question: {prompt}

Provide helpful, professional guidance. Keep responses concise and actionable."""
        else:
            enhanced_prompt = f"You are VAMP, an AI assistant for academic performance management. {prompt}"
        
        # Call Ollama API
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": enhanced_prompt,
                "stream": False
            },
            timeout=OLLAMA_TIMEOUT
        )
        
        if response.status_code == 200:
            data = response.json()
            return data.get("response", "I cannot provide guidance at this time.")
        else:
            return "Ollama service is unavailable. Please ensure it is running."
    
    except requests.exceptions.RequestException as e:
        print(f"Ollama error: {e}")
        return "Cannot reach Ollama. Please ensure the service is running on port 11434."
    except Exception as e:
        print(f"Unexpected error: {e}")
        return "An unexpected error occurred."

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
                manager = data.get('manager') or ''

                # Prefer helper that also loads existing contract JSON
                if create_or_load_profile is not None:
                    profile = create_or_load_profile(
                        staff_id=staff_id,
                        name=name,
                        position=position,
                        cycle_year=int(cycle_year),
                        faculty=faculty,
                        line_manager=manager,
                    )
                else:
                    profile = StaffProfile(
                        staff_id=staff_id,
                        name=name,
                        position=position,
                        cycle_year=int(cycle_year),
                        faculty=faculty,
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
        
        # First check if contract already exists (faster)
        contract_file = CONTRACTS_FOLDER / f"contract_{staff_id}_{cycle_year}.json"
        
        if contract_file.exists():
            # Use existing contract
            with open(contract_file, 'r') as f:
                ta_summary = json.load(f)
            
            if EXPECTATION_ENGINE_AVAILABLE and build_expectations_from_ta:
                expectations = build_expectations_from_ta(staff_id, int(cycle_year), ta_summary)
                
                # Save expectations
                expectations_file = CONTRACTS_FOLDER.parent / "staff_expectations" / f"expectations_{staff_id}_{cycle_year}.json"
                expectations_file.parent.mkdir(parents=True, exist_ok=True)
                
                with open(expectations_file, 'w') as f:
                    json.dump(expectations, f, indent=2)
                
                return jsonify({
                    "status": "success",
                    "tasks_count": len(expectations.get('tasks', [])),
                    "kpas_count": len(expectations.get('kpa_summary', {})),
                    "message": f"Generated {len(expectations.get('tasks', []))} tasks from existing contract"
                })
        
        # If no contract, parse from uploaded file
        if 'file' not in request.files:
            return jsonify({"error": "No file uploaded and no existing contract found"}), 400
        
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
                
                return jsonify({
                    "status": "success",
                    "tasks_count": len(expectations.get('tasks', [])),
                    "kpas_count": len(expectations.get('kpa_summary', {})),
                    "expectations_path": str(expectations_file)
                })
            except Exception as parse_error:
                print(f"TA parsing failed: {parse_error}")
                import traceback
                traceback.print_exc()
        else:
            print("TA parser not available. Using mock data.")
            return jsonify({
                "status": "success",
                "tasks_count": 12,
                "contract_path": "mock_contract.json",
                "note": "Using mock data for development"
            })
    
    except Exception as e:
        print(f"TA import error: {e}")
        return jsonify({"error": str(e)}), 500

# ============================================================
# EXPECTATIONS & PROGRESS
# ============================================================

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
        
        try:
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
        
        # Derive completion map (expected - missing) for the window
        task_rows = store.list_tasks_for_window(int(year), months)
        expected_task_ids = [r["task_id"] for r in task_rows]
        missing_ids = {t.get("task_id") for t in (progress.get("missing_tasks") or []) if isinstance(t, dict)}
        completed_ids = set([tid for tid in expected_task_ids if tid not in missing_ids])
        task_completion = {tid: True for tid in completed_ids}

        # Evidence list for Evidence Log (include top mapped task)
        evidence_rows = store.list_evidence(staff_id, int(year), month_bucket=month if month else None)
        evidence_list = []
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
            try:
                mappings = store.list_mappings_for_evidence(evd["evidence_id"])
                if mappings:
                    top_task_id = mappings[0]["task_id"]
                    top_task_title = mappings[0]["title"]
                    top_conf = float(mappings[0]["confidence"])
            except Exception:
                pass

            file_path = evd.get("file_path")
            filename = meta.get("filename") or (Path(file_path).name if file_path else None)

            evidence_list.append({
                "evidence_id": evd["evidence_id"],
                "date": meta.get("date") or meta.get("timestamp") or "",
                "filename": filename or "",
                "kpa": evd.get("kpa_code") or "",
                "month": evd.get("month_bucket") or "",
                "task": top_task_title or meta.get("task") or "",
                "task_id": top_task_id or meta.get("target_task_id") or "",
                "tier": evd.get("tier") or meta.get("tier") or "",
                "impact_summary": meta.get("impact_summary") or "",
                "confidence": top_conf if top_conf is not None else float(meta.get("confidence") or 0.0),
                "rating": evd.get("rating") or "",
                "file_path": file_path or "",
            })
        
        return jsonify({
            "progress": {
                "staff_id": staff_id,
                "year": int(year),
                "months": months,
                "total_tasks": int(progress.get("expected_tasks", 0)),
                "completed_count": int(progress.get("completed_tasks", 0)),
                "missing_tasks": progress.get("missing_tasks", []),
                "by_kpa": progress.get("by_kpa", {}),
            },
            "evidence": evidence_list,
            "task_completion": task_completion,
            "stats": {
                "total_tasks": int(progress.get("expected_tasks", 0)),
                "completed_tasks": int(progress.get("completed_tasks", 0)),
                "evidence_count": len(evidence_list)
            }
        })
    
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
        
        # Load contract
        contract_file = CONTRACTS_FOLDER / f"contract_{staff_id}_{year}.json"
        
        if not contract_file.exists():
            return jsonify({"error": "Contract not found. Import TA first."}), 404
        
        with open(contract_file, 'r') as f:
            contract_data = json.load(f)
        
        # Build expectations
        if EXPECTATION_ENGINE_AVAILABLE and build_expectations_from_ta:
            expectations = build_expectations_from_ta(staff_id, int(year), contract_data)
            
            # Save expectations
            expectations_file = CONTRACTS_FOLDER.parent / "staff_expectations" / f"expectations_{staff_id}_{year}.json"
            expectations_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(expectations_file, 'w') as f:
                json.dump(expectations, f, indent=2)
            
            return jsonify({
                "status": "success",
                "tasks_count": len(expectations.get('tasks', [])),
                "kpas_count": len(expectations.get('kpa_summary', {})),
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
            
            # Return the full expectations structure with tasks and by_month
            return jsonify(expectations_data)
        
        else:
            # Return mock data for development
            mock_expectations = generate_mock_expectations()
            mock_kpa_summary = {
                "Teaching & Learning": {"total": 4, "completed": 2, "progress": 50},
                "Research": {"total": 3, "completed": 1, "progress": 33},
                "Community Engagement": {"total": 2, "completed": 0, "progress": 0}
            }
            
            return jsonify({
                "expectations": mock_expectations,
                "kpa_summary": mock_kpa_summary,
                "tasks": mock_expectations,
                "by_month": {}
            })
    
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
        if expectations_file.exists():
            with open(expectations_file, 'r') as f:
                exp_data = json.load(f)
                by_month = exp_data.get('by_month', {})
                month_tasks = by_month.get(month, [])
        
        # Load evidence for this month
        evidence_file = EVIDENCE_FOLDER / f"evidence_{staff_id}_{year}.csv"
        evidence_count = 0
        evidence_by_kpa = {}
        
        if evidence_file.exists():
            import csv
            with open(evidence_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get('month_bucket', '').startswith(month):
                        evidence_count += 1
                        kpa = row.get('kpa_code', 'Unknown')
                        evidence_by_kpa[kpa] = evidence_by_kpa.get(kpa, 0) + 1
        
        # Calculate completion
        total_required = sum(task.get('minimum_count', 0) for task in month_tasks)
        complete = evidence_count >= total_required
        
        # Build AI analysis prompt
        ai_context = {
            'staff_id': staff_id,
            'month': month,
            'tasks': len(month_tasks),
            'evidence_count': evidence_count,
            'required': total_required
        }
        
        if complete:
            ai_prompt = f"The staff member has uploaded {evidence_count} evidence items for {month}, meeting the minimum requirement of {total_required}. Provide encouragement and suggest they prepare for next month."
        else:
            missing = total_required - evidence_count
            ai_prompt = f"The staff member has only uploaded {evidence_count} of {total_required} required evidence items for {month}. They are missing {missing} items. Provide constructive guidance on what evidence types they should focus on."
        
        ai_response = query_ollama(ai_prompt, ai_context)
        
        # Build detailed summary
        task_summary = []
        for task in month_tasks:
            kpa = task.get('kpa_code', 'Unknown')
            task_evidence = evidence_by_kpa.get(kpa, 0)
            task_required = task.get('minimum_count', 0)
            task_summary.append(f"{kpa}: {task_evidence}/{task_required} items")
        
        return jsonify({
            "complete": complete,
            "evidence_count": evidence_count,
            "required": total_required,
            "message": ai_response,
            "summary": "\n".join(task_summary) if task_summary else "No tasks for this month",
            "missing": f"Upload {total_required - evidence_count} more evidence items" if not complete else ""
        })
    
    except Exception as e:
        print(f"Month check error: {e}")
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
        
        results = []
        
        # Brain scorer is function-based (no NWUBrainScorer class)
        brain_enabled = bool(use_brain and BRAIN_SCORER_AVAILABLE and brain_score_evidence is not None)
        
        for idx, file in enumerate(files, 1):
            try:
                filename = secure_filename(file.filename)
                filepath = UPLOAD_FOLDER / filename
                file.save(str(filepath))
                
                # Extract text from file
                try:
                    file_text = extract_text_from_file(str(filepath))
                except Exception as e:
                    print(f"Text extraction failed for {filename}: {e}")
                    file_text = f"File: {filename}"
                
                # AI Classification using Ollama
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

                # Deterministic NWU Brain scoring (optional)
                brain_ctx = None
                if brain_enabled:
                    try:
                        brain_ctx = brain_score_evidence(path=Path(filepath), full_text=file_text, kpa_hint_code=None)
                    except Exception as e:
                        print(f"Brain scorer failed for {filename}: {e}")
                        brain_ctx = None
                
                # Map KPA name to KPA code (from brain first, else from Ollama classification)
                kpa_map = {
                    "teaching": "KPA1", "teaching & learning": "KPA1", "teaching and learning": "KPA1",
                    "ohs": "KPA2", "occupational health": "KPA2",
                    "research": "KPA3", "innovation": "KPA3",
                    "leadership": "KPA4", "academic leadership": "KPA4", "administration": "KPA4",
                    "social": "KPA5", "community": "KPA5", "social responsiveness": "KPA5"
                }
                kpa_code = None
                if brain_ctx and brain_ctx.get("primary_kpa_code"):
                    kpa_code = str(brain_ctx.get("primary_kpa_code"))
                if not kpa_code:
                    kpa_code = "KPA1"  # default
                    kpa_lower = classification.get("kpa", "").lower()
                    for key, code in kpa_map.items():
                        if key in kpa_lower:
                            kpa_code = code
                            break
                
                # Store in progress database
                evidence_id = None
                mapped_tasks = []
                try:
                    import sys
                    from pathlib import Path
                    sys.path.insert(0, str(Path(__file__).parent))
                    from progress_store import ProgressStore
                    from mapper import ensure_tasks, map_evidence_to_tasks
                    import hashlib
                    
                    # Initialize progress store
                    store = ProgressStore()
                    
                    # Ensure tasks exist for this staff/year
                    expectations_file = CONTRACTS_FOLDER.parent / "staff_expectations" / f"expectations_{staff_id}_{month[:4]}.json"
                    if expectations_file.exists():
                        with open(expectations_file, 'r') as f:
                            expectations = json.load(f)
                        ensure_tasks(store, staff_id=staff_id, year=int(month[:4]), expectations=expectations)
                    else:
                        ensure_tasks(store, staff_id=staff_id, year=int(month[:4]), expectations=None)
                    
                    # Generate evidence ID
                    evidence_id = f"ev_{staff_id}_{month}_{hashlib.md5(filename.encode()).hexdigest()[:8]}"
                    sha1 = hashlib.sha1(file_text.encode()).hexdigest()
                    
                    # If a target task was provided, prefer its KPA and map directly
                    if target_task_id:
                        try:
                            task_row = None
                            for r in store.list_tasks_for_window(int(month[:4]), [int(month.split('-')[1])], kpa_code=None):
                                if r["task_id"] == target_task_id:
                                    task_row = r
                                    break
                            if task_row is not None:
                                kpa_code = task_row["kpa_code"]
                        except Exception:
                            pass

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
                            "confidence": classification["confidence"],
                            "task": classification["task"],
                            "target_task_id": target_task_id or "",
                            "brain": brain_ctx or {},
                        }
                    )
                    
                    # Map evidence to tasks
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

                    # Targeted mapping (high confidence) - apply AFTER generic mapping to avoid overwrite
                    if target_task_id:
                        try:
                            store.upsert_mapping(
                                evidence_id,
                                target_task_id,
                                mapped_by="web_scan:targeted",
                                confidence=0.95,
                            )
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
                    "impact_summary": classification["impact_summary"],
                    "confidence": classification["confidence"],
                    "status": "Classified" if classification["confidence"] >= 0.6 else "Needs Review",
                    "evidence_id": evidence_id,
                    "mapped_tasks": len(mapped_tasks)
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

def extract_text_from_file(filepath: str) -> str:
    """Extract text from various file types"""
    # Simplified extraction - extend as needed
    ext = Path(filepath).suffix.lower()
    
    if ext == '.txt':
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    
    elif ext == '.pdf':
        try:
            import PyPDF2
            with open(filepath, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                text = ""
                for page in reader.pages:
                    text += page.extract_text()
                return text
        except:
            return f"PDF file: {Path(filepath).name}"
    
    else:
        return f"File: {Path(filepath).name}"

def classify_with_ollama(filename: str, content: str) -> Dict:
    """
    Use Ollama to classify evidence into KPAs
    """
    try:
        # Simple keyword-based classification as fallback
        content_lower = content.lower()
        filename_lower = filename.lower()
        combined = content_lower + " " + filename_lower
        
        # Keyword matching for quick classification
        kpa = "Teaching & Learning"  # Default
        confidence = 0.5
        
        if any(word in combined for word in ["research", "publication", "journal", "conference", "study"]):
            kpa = "Research"
            confidence = 0.7
        elif any(word in combined for word in ["community", "engagement", "outreach", "service"]):
            kpa = "Community Engagement"
            confidence = 0.7
        elif any(word in combined for word in ["teach", "lecture", "student", "curriculum", "module"]):
            kpa = "Teaching & Learning"
            confidence = 0.7
        elif any(word in combined for word in ["innovation", "impact", "technology", "development"]):
            kpa = "Innovation & Impact"
            confidence = 0.7
        elif any(word in combined for word in ["leadership", "management", "committee", "chair"]):
            kpa = "Leadership & Management"
            confidence = 0.7
        
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
            
            response = requests.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False
                },
                timeout=10  # Short timeout
            )
            
            if response.status_code == 200:
                data = response.json()
                ai_response = data.get("response", "").strip()
                
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
        
        except requests.exceptions.Timeout:
            print(f"Ollama timeout for {filename}, using keyword classification")
        except Exception as ollama_error:
            print(f"Ollama error for {filename}: {ollama_error}, using keyword classification")
        
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
        
        # Mock evidence data
        evidence = [
            {
                "date": "2025-01-10",
                "file": "lecture_notes.pdf",
                "kpa": "Teaching & Learning",
                "task": "Curriculum development",
                "impact": "Developed comprehensive lecture materials",
                "confidence": 0.85
            },
            {
                "date": "2025-01-15",
                "file": "research_proposal.docx",
                "kpa": "Research",
                "task": "Grant application",
                "impact": "Submitted NRF grant proposal",
                "confidence": 0.92
            }
        ]
        
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
        
        # Query Ollama
        answer = query_ollama(question, context)
        
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
        
        # Query Ollama
        guidance = query_ollama(f"Provide guidance: {question}", context)
        
        return jsonify({"guidance": guidance})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ============================================================
# REPORT GENERATION
# ============================================================

@app.route('/api/report/generate', methods=['GET'])
def generate_report():
    """
    Generate Performance Agreement report matching Excel format
    """
    try:
        staff_id = request.args.get('staff_id')
        year = request.args.get('year')
        
        if not staff_id or not year:
            return jsonify({"error": "Missing staff_id or year"}), 400
        
        # Load contract data
        contract_file = CONTRACTS_FOLDER / f"contract_{staff_id}_{year}.json"
        if not contract_file.exists():
            return jsonify({"error": "Contract not found"}), 404
        
        with open(contract_file, 'r') as f:
            contract_data = json.load(f)
        
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

if __name__ == '__main__':
    print("=" * 60)
    print("VAMP Web Server Starting")
    print("=" * 60)
    print(f"Ollama URL: {OLLAMA_BASE_URL}")
    print(f"Ollama Model: {OLLAMA_MODEL}")
    print(f"Upload Folder: {UPLOAD_FOLDER}")
    print(f"Data Folder: {DATA_FOLDER}")
    print("=" * 60)
    print("\nServer running at: http://localhost:5000")
    print("Open http://localhost:5000 in your browser")
    print("\nPress Ctrl+C to stop")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)
