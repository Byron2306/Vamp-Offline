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
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")  # Faster and better than 1b
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "180"))
PORT = int(os.getenv("PORT", "5000"))

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

IMPORTANT: Write in plain text only. NO asterisks (*), underscores (_), markdown, or special symbols. Write naturally as if speaking. Keep responses concise and actionable."""
        else:
            enhanced_prompt = f"You are VAMP, an AI assistant for academic performance management. Write in plain text only - no asterisks, markdown, or special symbols. {prompt}"
        
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

                # Immediately ensure tasks are present in the progress DB
                try:
                    from progress_store import ProgressStore
                    from mapper import ensure_tasks
                    store = ProgressStore()
                    ensure_tasks(store, staff_id=staff_id, year=int(cycle_year), expectations=expectations)
                except Exception as e:
                    print(f"Warning: could not upsert tasks after import: {e}")

                return jsonify({
                    "status": "success",
                    "tasks_count": len(expectations.get('tasks', [])),
                    "kpas_count": len(expectations.get('kpa_summary', {})),
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
            print("TA parser not available.")
            return jsonify({"error": "Task Agreement parser not available. Please ensure the expectation engine is installed and import a TA."}), 500
    
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

            file_path = evd.get("file_path")
            filename = meta.get("filename") or (Path(file_path).name if file_path else None)

            # Extract rating from brain scorer if available
            brain_data = meta.get("brain", {})
            rating = brain_data.get("rating") if isinstance(brain_data, dict) else None
            rating_label = brain_data.get("rating_label", "") if isinstance(brain_data, dict) else ""
            user_enhanced = meta.get("user_enhanced", False)
            
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
                "user_enhanced": user_enhanced,
                "brain": brain_data,
                "meta": meta,
                "file_path": file_path or "",
            })
        
        resp = {
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
                            base_task = task_index.get(task.get('task_id')) if task.get('task_id') else None
                            hashed_id = None
                            if base_task and month_lookup and 'hashed_ids' in base_task:
                                hashed_id = base_task['hashed_ids'].get(month_lookup)

                            task['id'] = hashed_id or task.get('task_id')
                            # Normalize field names for UI
                            if 'title' not in task and 'output' in task:
                                task['title'] = task['output']
                            task['minimum_count'] = task.get('min_required') or task.get('minimum_count') or 1
                            task['stretch_count'] = task.get('stretch_target') or task.get('stretch_count') or task['minimum_count']

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
        # Provide default messages that work without AI
        if complete:
            ai_response = f"Great work! All {tasks_met} required tasks for {month} have been completed with {evidence_count} evidence items."
        else:
            ai_response = f"Progress update: {tasks_met} of {tasks_total} tasks complete. Focus on uploading evidence for the remaining {tasks_total - tasks_met} tasks."
        
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
        
        return jsonify({
            "complete": complete,
            "tasks_met": tasks_met,
            "tasks_total": tasks_total,
            "evidence_count": evidence_count,
            "message": ai_response,
            "summary": "\n".join(task_summary_lines) if task_summary_lines else "No tasks for this month",
            "task_status": task_status,
            "missing": f"{tasks_total - tasks_met} tasks still need evidence" if not complete else ""
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
        asserted_mapping = request.form.get('asserted_mapping') == 'true'  # User pre-locked evidence to task
        
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
                
                # AI Classification using Ollama (skip if asserted mapping)
                if asserted_mapping and target_task_id:
                    # User asserted this evidence belongs to the target task
                    # Skip AI classification entirely, use minimal classification
                    classification = {
                        "kpa": "Asserted",
                        "task": "User-selected task",
                        "tier": "N/A",
                        "impact_summary": "Evidence directly linked to task by user (asserted relevance)",
                        "confidence": 1.0
                    }
                    use_brain = False  # Skip brain scorer too
                elif use_contextual:
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

                # Deterministic NWU Brain scoring (prioritize this for accuracy)
                # Skip brain scorer if user has asserted the mapping to respect their decision
                brain_ctx = None
                if brain_enabled and not (asserted_mapping and target_task_id):
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
                
                # Map KPA name to KPA code (from brain first, else from Ollama classification)
                kpa_map = {
                    "teaching": "KPA1", "teaching & learning": "KPA1", "teaching and learning": "KPA1",
                    "ohs": "KPA2", "occupational health": "KPA2", "occupational health & safety": "KPA2",
                    "research": "KPA3", "innovation": "KPA3", "research & innovation": "KPA3",
                    "leadership": "KPA4", "academic leadership": "KPA4", "administration": "KPA4",
                    "social": "KPA5", "community": "KPA5", "social responsiveness": "KPA5", "engagement": "KPA5"
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
                            "confidence": classification["confidence"],
                            "task": classification["task"],
                            "target_task_id": target_task_id or "",
                            "brain": brain_ctx or {},
                        }
                    )
                    
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


def classify_with_ollama_raw(prompt: str) -> Dict:
    """
    Raw Ollama classification with custom prompt.
    Returns parsed JSON classification result.
    """
    try:
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "format": "json"
            },
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            ai_response = data.get("response", "").strip()
            
            # Parse JSON response
            import json
            try:
                return json.loads(ai_response)
            except json.JSONDecodeError:
                # Fallback if not valid JSON
                return {
                    "kpa": "KPA1",
                    "task": "Classification failed",
                    "tier": "Unknown",
                    "impact_summary": ai_response[:200],
                    "confidence": 0.5
                }
        else:
            raise Exception(f"Ollama returned status {response.status_code}")
            
    except Exception as e:
        print(f"Ollama raw classification error: {e}")
        raise


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
        user_description = data.get('user_description', '').strip()
        target_task_id = data.get('target_task_id')  # Optional
        
        if not evidence_id or not staff_id:
            return jsonify({"error": "Missing evidence_id or staff_id"}), 400
        
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
        evidence_rows = store.list_evidence(staff_id=staff_id)
        evidence_item = None
        for row in evidence_rows:
            if row.get("evidence_id") == evidence_id:
                evidence_item = row
                break
        
        if not evidence_item:
            return jsonify({"error": "Evidence not found"}), 404
        
        # Get original values
        old_kpa = evidence_item.get("kpa_code", "Unknown")
        old_confidence = float(evidence_item.get("meta", {}).get("confidence", 0.0))
        file_path = evidence_item.get("file_path", "")
        filename = evidence_item.get("meta", {}).get("filename", "")
        
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
        
        if not staff_id:
            return jsonify({"error": "Missing staff_id"}), 400
        
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from progress_store import ProgressStore
        
        store = ProgressStore()
        
        # Get all evidence for staff
        evidence_rows = store.list_evidence(staff_id=staff_id)
        
        # Filter by month if specified
        if month and month != 'all':
            evidence_rows = [r for r in evidence_rows if r.get("month_bucket", "").startswith(month)]
        
        # Group by KPA and calculate averages
        kpa_scores = {}
        kpa_counts = {}
        
        for row in evidence_rows:
            kpa_code = row.get("kpa_code", "")
            if not kpa_code:
                continue
            
            # Try to get rating from brain scorer results
            rating = None
            meta = row.get("meta", {})
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
                        kpa_scores[kpa_code] += rating
                        kpa_counts[kpa_code] += 1
                except (ValueError, TypeError):
                    pass
        
        # Calculate averages
        averages = {}
        for kpa_code in kpa_scores:
            if kpa_counts[kpa_code] > 0:
                averages[kpa_code] = round(kpa_scores[kpa_code] / kpa_counts[kpa_code], 2)
        
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
            "month": month,
            "scores": averages,
            "counts": kpa_counts,
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

@app.route('/api/voice/status', methods=['GET'])
def voice_status():
    """Get ElevenLabs TTS status"""
    try:
        if not ELEVENLABS_AVAILABLE:
            return jsonify({
                "available": False,
                "error": "ElevenLabs TTS not available"
            })
        
        client = get_tts_client()
        quota = client.check_quota()
        voice_info = client.get_voice_info()
        
        return jsonify({
            "available": True,
            "engine": "elevenlabs",
            "voice_id": client.VOICE_ID,
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
        voice_name = data.get('voice_name', 'vamp_voice')
        
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
    """Convert text to speech using ElevenLabs"""
    try:
        if not ELEVENLABS_AVAILABLE:
            return jsonify({"error": "ElevenLabs TTS not available"}), 503
        
        data = request.json
        text = data.get('text')
        
        if not text:
            return jsonify({"error": "No text provided"}), 400
        
        # Sanitize text first
        clean_text = sanitize_for_speech(text)
        
        # Generate speech using ElevenLabs
        audio_path = text_to_speech(clean_text)
        
        if audio_path is None:
            return jsonify({"error": "Speech generation failed"}), 500
        
        # Return audio file info
        return jsonify({
            "success": True,
            "audio_url": f"/api/voice/audio/{audio_path.name}",
            "filename": audio_path.name,
            "engine": "elevenlabs"
        })
    
    except Exception as e:
        print(f"Voice synthesis error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/voice/audio/<filename>')
def voice_audio(filename):
    """Serve generated audio files from ElevenLabs"""
    try:
        if not ELEVENLABS_AVAILABLE:
            return jsonify({"error": "ElevenLabs TTS not available"}), 503
        
        client = get_tts_client()
        audio_path = client.cache_dir / filename
        
        if not audio_path.exists():
            return jsonify({"error": "Audio file not found"}), 404
        
        return send_from_directory(str(client.cache_dir), filename, mimetype='audio/mpeg')
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/vamp/ask-voice', methods=['POST'])
def ask_vamp_voice():
    """
    Ask VAMP for AI guidance with voice response using ElevenLabs
    """
    try:
        data = request.json
        question = data.get('question')
        context = data.get('context', {})
        
        if not question:
            return jsonify({"error": "No question provided"}), 400
        
        # Query Ollama for text response
        answer = query_ollama(question, context)
        
        # Sanitize text for speech (remove asterisks, markdown, etc.)
        if ELEVENLABS_AVAILABLE and sanitize_for_speech:
            clean_answer = sanitize_for_speech(answer)
        else:
            clean_answer = answer
        
        # Generate voice using ElevenLabs
        audio_url = None
        if ELEVENLABS_AVAILABLE:
            try:
                audio_path = text_to_speech(clean_answer)
                if audio_path:
                    # Serve from cache directory
                    audio_url = f"/api/voice/audio/{audio_path.name}"
            except Exception as voice_error:
                print(f"ElevenLabs voice generation failed (non-fatal): {voice_error}")
        
        return jsonify({
            "answer": clean_answer,
            "audio_url": audio_url,
            "has_voice": audio_url is not None,
            "voice_engine": "elevenlabs" if ELEVENLABS_AVAILABLE else "none"
        })
    
    except Exception as e:
        print(f"Ask VAMP voice error: {e}")
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
    print(f"\nServer running at: http://localhost:{PORT}")
    print(f"Open http://localhost:{PORT} in your browser")
    print("\nPress Ctrl+C to stop")
    print("=" * 60)
    
    # Run without the debug auto-reloader for stable testing sessions.
    # Keep threaded=True for concurrency; explicit `use_reloader=False` prevents restarts.
    app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False, threaded=True)
