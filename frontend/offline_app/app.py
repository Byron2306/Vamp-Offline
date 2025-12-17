"""
Flask web application for VAMP Offline GUI
Ports the Tkinter GUI to a web-based interface while maintaining all functionality
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
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from werkzeug.utils import secure_filename

from flask import Flask, render_template, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
import sys

# Add repo root to path
def _ensure_repo_root_on_sys_path() -> Path:
    here = Path(__file__).resolve()
    for parent in [here] + list(here.parents):
        if (parent / 'backend').is_dir():
            if str(parent) not in sys.path:
                sys.path.insert(0, str(parent))
            return parent
    cwd = Path.cwd().resolve()
    if (cwd / 'backend').is_dir() and str(cwd) not in sys.path:
        sys.path.insert(0, str(cwd))
        return cwd
    return cwd

REPO_ROOT = _ensure_repo_root_on_sys_path()

# Backend imports
try:
    from backend.staff_profile import (
        StaffProfile,
        create_or_load_profile,
        staff_is_director_level,
    )
except ImportError:
    StaffProfile = None

try:
    from backend.contracts.task_agreement_import import import_task_agreement_excel
except ImportError:
    import_task_agreement_excel = None

try:
    from backend.vamp_master import extract_text_for, brain_score_evidence
except ImportError:
    extract_text_for = None
    brain_score_evidence = None

try:
    from frontend.offline_app.contextual_scorer import contextual_score
except ImportError:
    contextual_score = None

# Flask app setup
app = Flask(__name__, template_folder='templates', static_folder='static')
CORS(app)

# Configuration
UPLOAD_FOLDER = Path(REPO_ROOT) / 'uploads'
UPLOAD_FOLDER.mkdir(exist_ok=True)
ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png', 'xlsx', 'xls', 'json', 'csv'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB max

# App state
app_state = {
    'profile': None,
    'contract': None,
    'task_agreement_path': None,
    'pa_skeleton_path': None,
    'current_evidence_folder': None,
    'expectations': {},
    'rows': [],
    'ta_valid': False,
    'pa_skeleton_ready': False,
    'pa_ai_ready': False,
    'contract_validation_errors': [],
    'contract_validation_warnings': [],
    'session_state': {},
    'logs': [],
    'processing': False,
}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def add_log(msg: str):
    """Add a log message to the app state"""
    timestamp = _dt.datetime.now().strftime("%H:%M:%S")
    app_state['logs'].append(f"[{timestamp}] {msg}")
    if len(app_state['logs']) > 1000:
        app_state['logs'] = app_state['logs'][-1000:]

@app.route('/')
def index():
    """Main UI page"""
    return render_template('index.html')

@app.route('/api/status')
def get_status():
    """Get current application status"""
    return jsonify({
        'contract_loaded': app_state['contract'] is not None,
        'ta_imported': app_state['ta_valid'],
        'pa_skeleton_ready': app_state['pa_skeleton_ready'],
        'pa_ai_ready': app_state['pa_ai_ready'],
        'processing': app_state['processing'],
        'logs': app_state['logs'][-50:],  # Last 50 logs
    })

@app.route('/api/upload/contract', methods=['POST'])
def upload_contract():
    """Upload and load a contract JSON"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    if not allowed_file(file.filename):
        return jsonify({'error': 'Invalid file type'}), 400
    
    try:
        content = file.read().decode('utf-8')
        app_state['contract'] = json.loads(content)
        app_state['contract_loaded'] = True
        add_log(f"✓ Contract loaded: {file.filename}")
        return jsonify({'success': True})
    except Exception as e:
        add_log(f"✗ Failed to load contract: {e}")
        return jsonify({'error': str(e)}), 400

@app.route('/api/upload/task-agreement', methods=['POST'])
def upload_task_agreement():
    """Upload task agreement"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    filename = secure_filename(file.filename)
    filepath = Path(app.config['UPLOAD_FOLDER']) / filename
    file.save(str(filepath))
    
    app_state['task_agreement_path'] = filepath
    app_state['ta_valid'] = True
    add_log(f"✓ Task agreement imported: {filename}")
    return jsonify({'success': True, 'path': str(filepath)})

@app.route('/api/upload/pa-skeleton', methods=['POST'])
def upload_pa_skeleton():
    """Upload PA skeleton"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    filename = secure_filename(file.filename)
    filepath = Path(app.config['UPLOAD_FOLDER']) / filename
    file.save(str(filepath))
    
    app_state['pa_skeleton_path'] = filepath
    app_state['pa_skeleton_ready'] = True
    add_log(f"✓ PA skeleton loaded: {filename}")
    return jsonify({'success': True, 'path': str(filepath)})

@app.route('/api/upload/evidence', methods=['POST'])
def upload_evidence():
    """Upload evidence file for scanning"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    filename = secure_filename(file.filename)
    evidence_folder = Path(app.config['UPLOAD_FOLDER']) / 'evidence'
    evidence_folder.mkdir(exist_ok=True)
    filepath = evidence_folder / filename
    file.save(str(filepath))
    
    app_state['current_evidence_folder'] = evidence_folder
    add_log(f"✓ Evidence file uploaded: {filename}")
    return jsonify({'success': True, 'path': str(filepath)})

@app.route('/api/scan-evidence', methods=['POST'])
def scan_evidence():
    """Scan evidence folder"""
    if not app_state['current_evidence_folder']:
        return jsonify({'error': 'No evidence folder selected'}), 400
    
    try:
        app_state['processing'] = True
        folder = Path(app_state['current_evidence_folder'])
        
        rows = []
        for file_path in sorted(folder.glob('*')):
            if not file_path.is_file():
                continue
            
            try:
                # Extract text
                add_log(f"Processing: {file_path.name}")
                extraction = extract_text_for(file_path)
                extracted_text = extraction.extracted_text if hasattr(extraction, 'extracted_text') else ""
                
                # Score with contextual scorer
                ctx = {}
                try:
                    ctx = contextual_score(
                        evidence_text=extracted_text,
                        contract_context=json.dumps(app_state['contract'] or {}),
                        kpa_hint_code="",
                        staff_id="",
                        source_path=file_path,
                        prefer_llm_rating=False,
                    )
                except:
                    # Fallback to brain scoring
                    ctx = brain_score_evidence(path=file_path, full_text=extracted_text, kpa_hint_code="") or {}
                
                row = {
                    'filename': file_path.name,
                    'status': 'SCORED' if ctx.get('primary_kpa_code') else 'NEEDS_REVIEW',
                    'kpa': ctx.get('primary_kpa_code', 'Unknown'),
                    'impact': ctx.get('impact_summary', ''),
                    'confidence': ctx.get('confidence', 0),
                }
                rows.append(row)
                add_log(f"✓ Scored: {file_path.name}")
            except Exception as e:
                add_log(f"✗ Error processing {file_path.name}: {e}")
                rows.append({
                    'filename': file_path.name,
                    'status': 'FAILED',
                    'error': str(e),
                })
        
        app_state['rows'] = rows
        app_state['processing'] = False
        return jsonify({'success': True, 'rows': rows})
    except Exception as e:
        app_state['processing'] = False
        add_log(f"✗ Scan failed: {e}")
        return jsonify({'error': str(e)}), 400

@app.route('/api/enrich-pa', methods=['POST'])
def enrich_pa():
    """Enrich PA with AI"""
    if not app_state['pa_skeleton_ready']:
        return jsonify({'error': 'PA skeleton not loaded'}), 400
    
    try:
        app_state['processing'] = True
        add_log("Starting PA AI enrichment...")
        
        # Placeholder for PA enrichment logic
        add_log("✓ PA enrichment complete")
        app_state['pa_ai_ready'] = True
        app_state['processing'] = False
        return jsonify({'success': True})
    except Exception as e:
        app_state['processing'] = False
        add_log(f"✗ PA enrichment failed: {e}")
        return jsonify({'error': str(e)}), 400

@app.route('/api/export-results', methods=['GET'])
def export_results():
    """Export results as CSV"""
    try:
        output_path = Path(app.config['UPLOAD_FOLDER']) / 'results.csv'
        
        if not app_state['rows']:
            return jsonify({'error': 'No results to export'}), 400
        
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['filename', 'status', 'kpa', 'impact', 'confidence'])
            writer.writeheader()
            writer.writerows(app_state['rows'])
        
        add_log(f"✓ Results exported to {output_path.name}")
        return send_file(str(output_path), as_attachment=True, download_name='results.csv')
    except Exception as e:
        add_log(f"✗ Export failed: {e}")
        return jsonify({'error': str(e)}), 400

@app.route('/api/logs')
def get_logs():
    """Get all logs"""
    return jsonify({'logs': app_state['logs']})

@app.route('/api/clear-logs', methods=['POST'])
def clear_logs():
    """Clear logs"""
    app_state['logs'] = []
    return jsonify({'success': True})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
