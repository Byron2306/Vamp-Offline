# VAMP Offline - Web UI Port

## Overview

The VAMP Offline application has been successfully ported from a Tkinter desktop GUI to a modern, web-based HTML/Flask interface. All functionality from the original GUI has been preserved and enhanced with a responsive design.

## What Changed

### 1. **environment.yml - Fixed Dependencies**
   - Added `ollama` - for contextual scoring
   - Added `flask` - web framework
   - Added `flask-cors` - cross-origin support
   - Added `python-dotenv` - environment configuration

### 2. **New Web Application Files**

#### `/frontend/offline_app/app.py`
- Flask web server implementation
- RESTful API endpoints for all operations
- Session state management
- File upload handling
- Evidence scanning integration
- Activity logging

#### `/frontend/offline_app/templates/index.html`
- Modern, responsive HTML interface
- Three-panel layout matching original design:
  1. **Top Panel**: Document loading (Contract, TA, PA Skeleton)
  2. **Middle Panel**: Evidence scanning and table view
  3. **Bottom Panel**: Activity logs and filters

#### `/frontend/offline_app/static/style.css`
- Dark modern theme (matching original color scheme)
- Responsive design for mobile/tablet support
- Smooth animations and transitions
- Professional UI/UX

#### `/frontend/offline_app/static/app.js`
- Frontend logic and state management
- API communication
- Real-time UI updates
- File upload handling
- Log streaming
- Keyboard shortcuts (Ctrl+S for scan, Ctrl+E for export)

#### `/run_web.py`
- Convenient entry point to start the web server
- Displays startup information
- Runs on `http://localhost:5000`

## Features Preserved

✅ **Document Loading**
- Load contract JSON
- Import task agreements (XLSX)
- Load PA skeleton files

✅ **Evidence Scanning**
- Upload evidence files (PDF, images, documents)
- Automatic text extraction
- Contextual scoring with Ollama
- Brain scoring fallback

✅ **Results Management**
- View scored evidence in table format
- Filter by status, KPA, type
- Export results to CSV

✅ **Activity Monitoring**
- Real-time activity log
- Processing status indicators
- Error tracking

✅ **Status Indicators**
- Contract loaded badge
- TA imported badge
- PA ready badge
- Enrichment status badge

## How to Run

### Prerequisites
```bash
# Install dependencies (already in environment.yml)
pip install flask flask-cors ollama
```

### Start the Web Server
```bash
python run_web.py
```

The server will start on `http://localhost:5000`

### Alternative: Start with Flask directly
```bash
cd /workspaces/Vamp-Offline
FLASK_APP=frontend/offline_app/app.py python -m flask run --host=0.0.0.0 --port=5000
```

## Usage Workflow

1. **Load Documents** (Top Panel)
   - Upload contract JSON
   - Import task agreement XLSX
   - Load PA skeleton XLSX
   - Start AI enrichment

2. **Scan Evidence** (Middle Panel)
   - Upload evidence files
   - Click "Scan Evidence" to process
   - View results in the table

3. **Review & Export** (Bottom Panel)
   - Check activity logs
   - Use filters to find specific evidence
   - Export results as CSV

## API Endpoints

### Status & Info
- `GET /api/status` - Get current application status
- `GET /api/logs` - Get activity logs
- `POST /api/clear-logs` - Clear logs

### File Uploads
- `POST /api/upload/contract` - Upload contract JSON
- `POST /api/upload/task-agreement` - Upload TA XLSX
- `POST /api/upload/pa-skeleton` - Upload PA skeleton
- `POST /api/upload/evidence` - Upload evidence file

### Processing
- `POST /api/scan-evidence` - Scan and score evidence
- `POST /api/enrich-pa` - Enrich PA with AI
- `GET /api/export-results` - Export results as CSV

## Browser Compatibility

- ✅ Chrome/Chromium (recommended)
- ✅ Firefox
- ✅ Safari
- ✅ Edge
- ✅ Mobile browsers (responsive design)

## Keyboard Shortcuts

- `Ctrl+S` or `Cmd+S` - Scan evidence
- `Ctrl+E` or `Cmd+E` - Export results

## File Size Limits

- Maximum file size: 500MB
- Supported formats:
  - Contracts: JSON
  - Task Agreements: XLSX, XLS
  - PA Skeleton: XLSX, XLS
  - Evidence: PDF, JPG, JPEG, PNG, XLSX, XLS, JSON, CSV

## Troubleshooting

### Port 5000 already in use
```bash
# Use a different port
FLASK_ENV=development python run_web.py --port=5001
```

### Templates not found
Ensure you're running from the repository root:
```bash
cd /workspaces/Vamp-Offline
python run_web.py
```

### Import errors
Make sure all backend modules are available:
```bash
python -c "from frontend.offline_app.app import app; print('OK')"
```

## Performance Notes

- First load may take a few seconds due to module imports
- Evidence scanning performance depends on file size and system resources
- Contextual scoring requires Ollama to be running (if enabled)
- Large batches (100+ files) may take several minutes to process

## Future Enhancements

Potential improvements for the web UI:
- Real-time progress bars for batch processing
- Drag-and-drop file upload
- WebSocket support for live log streaming
- Database persistence for historical data
- User authentication and roles
- Advanced filtering and search
- Data visualization dashboards
- API documentation (Swagger/OpenAPI)

## Technical Architecture

```
┌─────────────────────────────────────────┐
│   Browser (HTML/CSS/JS Frontend)        │
│   - index.html                          │
│   - style.css                           │
│   - app.js                              │
└────────────┬────────────────────────────┘
             │ HTTP/JSON
             ↓
┌─────────────────────────────────────────┐
│   Flask Web Server (app.py)             │
│   - Route handlers                      │
│   - API endpoints                       │
│   - File upload management              │
│   - Session state                       │
└────────────┬────────────────────────────┘
             │
             ↓
┌─────────────────────────────────────────┐
│   Backend Modules                       │
│   - vamp_master.py (text extraction)    │
│   - contextual_scorer.py (scoring)      │
│   - evidence_store.py (storage)         │
│   - nwu_brain_scorer.py (fallback)      │
│   - ... other backend modules           │
└─────────────────────────────────────────┘
```

## Original Tkinter GUI

The original Tkinter GUI (`offline_app_gui_llm_csv.py`) is still available if you prefer to use it:

```bash
python frontend/offline_app/offline_app_gui_llm_csv.py
```

However, the web interface is recommended for:
- Cross-platform compatibility
- Better responsiveness
- Easier deployment
- Modern UI/UX
- Remote access capability

## License

Same as the original VAMP project.

---

**Status**: ✅ Web UI fully functional and all features preserved
**Last Updated**: December 17, 2025
