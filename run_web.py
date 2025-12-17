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
    from backend.staff_profile import StaffProfile
    STAFF_PROFILE_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Could not import StaffProfile: {e}")
    STAFF_PROFILE_AVAILABLE = False
    StaffProfile = None

try:
    from backend.contracts.task_agreement_import import parse_task_agreement
    TASK_AGREEMENT_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Could not import task_agreement_import: {e}")
    TASK_AGREEMENT_AVAILABLE = False
    parse_task_agreement = None

try:
    from backend.expectation_engine import ExpectationEngine
    EXPECTATION_ENGINE_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Could not import ExpectationEngine: {e}")
    EXPECTATION_ENGINE_AVAILABLE = False
    ExpectationEngine = None

try:
    from backend.batch7_scorer import NWUBrainScorer
    BRAIN_SCORER_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Could not import NWUBrainScorer: {e}")
    BRAIN_SCORER_AVAILABLE = False
    NWUBrainScorer = None

print("Running in mock mode for unavailable backend modules")

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
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama2")

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
            timeout=60
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
    return send_from_directory('.', 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('.', path)

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
                # Try with all parameters
                profile = StaffProfile(
                    staff_id=staff_id,
                    cycle_year=int(cycle_year)
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
    Import Task Agreement from uploaded Excel file
    """
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file uploaded"}), 400
        
        file = request.files['file']
        staff_id = request.form.get('staff_id')
        cycle_year = request.form.get('cycle_year')
        
        if not staff_id or not cycle_year:
            return jsonify({"error": "Missing staff_id or cycle_year"}), 400
        
        # Save file
        filename = secure_filename(file.filename)
        filepath = UPLOAD_FOLDER / filename
        file.save(str(filepath))
        
        # Parse Task Agreement
        if TASK_AGREEMENT_AVAILABLE:
            try:
                # Try with just filepath (check function signature)
                contract_data = parse_task_agreement(str(filepath))
                
                # Add staff info if not in contract
                if 'staff_id' not in contract_data:
                    contract_data['staff_id'] = staff_id
                if 'cycle_year' not in contract_data:
                    contract_data['cycle_year'] = int(cycle_year)
                
                # Save contract
                contract_file = CONTRACTS_FOLDER / f"contract_{staff_id}_{cycle_year}.json"
                contract_file.parent.mkdir(parents=True, exist_ok=True)
                
                with open(contract_file, 'w') as f:
                    json.dump(contract_data, f, indent=2)
                
                return jsonify({
                    "status": "success",
                    "tasks_count": len(contract_data.get('tasks', [])),
                    "contract_path": str(contract_file)
                })
            except Exception as parse_error:
                print(f"TA parsing failed: {parse_error}. Using mock data.")
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
# EXPECTATIONS
# ============================================================

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
        
        # Try to load contract
        contract_file = CONTRACTS_FOLDER / f"contract_{staff_id}_{year}.json"
        
        if contract_file.exists():
            with open(contract_file, 'r') as f:
                contract_data = json.load(f)
            
            # Generate expectations from contract
            if EXPECTATION_ENGINE_AVAILABLE:
                try:
                    engine = ExpectationEngine(contract_data)
                    expectations = engine.generate_expectations()
                except Exception as e:
                    print(f"ExpectationEngine error: {e}. Using mock data.")
                    expectations = generate_mock_expectations()
            else:
                expectations = generate_mock_expectations()
            
            # Calculate KPA summary
            kpa_summary = {}
            for exp in expectations:
                kpa = exp.get('kpa', 'Unknown')
                if kpa not in kpa_summary:
                    kpa_summary[kpa] = {"total": 0, "completed": 0, "progress": 0}
                
                kpa_summary[kpa]["total"] += 1
                if exp.get('progress', 0) >= 100:
                    kpa_summary[kpa]["completed"] += 1
            
            # Calculate progress percentages
            for kpa_data in kpa_summary.values():
                if kpa_data["total"] > 0:
                    kpa_data["progress"] = int((kpa_data["completed"] / kpa_data["total"]) * 100)
            
            return jsonify({
                "expectations": expectations,
                "kpa_summary": kpa_summary
            })
        
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
                "kpa_summary": mock_kpa_summary
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
        use_brain = request.form.get('use_brain') == 'true'
        use_contextual = request.form.get('use_contextual') == 'true'
        
        results = []
        
        # Initialize scorers
        brain_scorer = None
        if use_brain and BRAIN_SCORER_AVAILABLE:
            try:
                brain_scorer = NWUBrainScorer()
            except Exception as e:
                print(f"Brain scorer initialization failed: {e}")
                brain_scorer = None
        
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
                
                # Store result
                result = {
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "file": filename,
                    "kpa": classification["kpa"],
                    "task": classification["task"],
                    "tier": classification["tier"],
                    "impact_summary": classification["impact_summary"],
                    "confidence": classification["confidence"],
                    "status": "Classified" if classification["confidence"] >= 0.6 else "Needs Review"
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
    Generate Performance Agreement report
    """
    try:
        staff_id = request.args.get('staff_id')
        period = request.args.get('period', 'final')
        
        # Mock report generation
        report_path = f"reports/PA_{staff_id}_{period}_{datetime.now().strftime('%Y%m%d')}.xlsx"
        
        return jsonify({
            "status": "success",
            "path": report_path,
            "kpas_count": 5,
            "tasks_count": 12,
            "evidence_count": 24
        })
    
    except Exception as e:
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
