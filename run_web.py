#!/usr/bin/env python3
"""
Run script for VAMP Offline Web Application

This script starts the Flask web server for the VAMP offline performance management system.
The web UI provides the same functionality as the original Tkinter GUI but in a browser-based interface.

Usage:
    python run_web.py
    
Then open your browser to: http://localhost:5000
"""

import sys
import os
from pathlib import Path

# Ensure repo root is in sys.path
here = Path(__file__).resolve()
for parent in [here] + list(here.parents):
    if (parent / 'backend').is_dir():
        if str(parent) not in sys.path:
            sys.path.insert(0, str(parent))
        os.chdir(parent)
        break

# Import and run the Flask app
from frontend.offline_app.app import app

if __name__ == '__main__':
    print("""
    ╔════════════════════════════════════════════════╗
    ║   VAMP Offline - Performance Management         ║
    ║   Web Server Starting...                        ║
    ╚════════════════════════════════════════════════╝
    
    🌐 Open your browser to: http://localhost:5000
    
    Press Ctrl+C to stop the server
    """)
    
    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False)
