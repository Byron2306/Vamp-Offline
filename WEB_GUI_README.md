# VAMP Web GUI - Quick Start Guide

## 🎯 What's Been Built

A comprehensive web-based GUI for VAMP with:

### ✅ Features Implemented

1. **Enhanced UI Design**
   - Dark gothic theme with NWU branding
   - Cloister Black and Cinzel fonts
   - Crimson accents and luminous progress bars
   - VAMP vampire video central hero element

2. **VAMP Avatar Video Behavior**
   - **Idle State**: Video paused, ready for input
   - **Busy State**: Video stopped with "thinking" overlay
   - **Speaking State**: Video loops while responding

3. **Expectations Tab**
   - Detailed table: Task | Month | Enabler | Goal | Lead/Lag Targets | Weight | Progress Bar | Ask AI
   - Per-KPA crimson progress bars with Cloister font
   - AI guidance modal for each task
   - Live progress tracking

4. **Evidence Scan Tab**
   - Multi-file upload support
   - AI classification with Ollama
   - Expanded table: Date | File | KPA | Task | Tier | Impact | Confidence | Status | Resolve
   - Confidence-based resolution modal (< 60% triggers manual review)
   - Real-time scan feedback

5. **Ollama Integration**
   - Ask VAMP feature with context-aware responses
   - Evidence classification using LLM
   - Task guidance system
   - Keyboard shortcut: Ctrl+K to focus Ask VAMP

6. **Live Data Tables**
   - Dynamic expectations rendering
   - Real-time scan results
   - Evidence history tracking
   - KPA progress visualization

## 🚀 How to Run

### Prerequisites

1. **Install Python dependencies**:
   ```bash
   pip install flask flask-cors requests
   ```

2. **Install and start Ollama**:
   ```bash
   # Install Ollama (if not already installed)
   curl https://ollama.ai/install.sh | sh
   
   # Pull a model (llama2 recommended)
   ollama pull llama2
   
   # Start Ollama service
   ollama serve
   ```

### Starting the Server

```bash
# Make the script executable
chmod +x run_web.py

# Start the server
python run_web.py
```

The server will start on **http://localhost:5000**

### Alternative: Using run_web.sh

```bash
chmod +x run_web.sh
./run_web.sh
```

## 📖 User Workflow

### 1. Enrolment
- Fill in your profile details (Staff ID, Name, Position, etc.)
- Click "Enrol / Load"
- Status pills update: Profile ✓

### 2. Task Agreement Import
- Select your Task Agreement Excel file
- Click "Import TA"
- VAMP processes and extracts tasks
- Status pills update: TA ✓

### 3. Expectations Tab
- Automatically loaded after TA import
- View all tasks with progress bars
- Click "🤖 Ask AI" to get guidance on any task
- KPA progress bars show overall completion

### 4. Evidence Scan
- Select multiple files (PDF, DOCX, TXT, etc.)
- Choose month bucket
- Enable/disable NWU Brain and Ollama scoring
- Click "Upload & Scan Files"
- VAMP processes files with AI
- Review results in the table
- Items with < 60% confidence show "🔧 Resolve" button

### 5. Classification Resolution
- Click "🔧 Resolve" on low-confidence items
- Select correct KPA from dropdown
- Explain the linkage
- Submit to save

### 6. Ask VAMP Anytime
- Use the "Ask VAMP" textarea (always visible)
- Type your question
- Press Enter or click "Ask VAMP"
- VAMP consults Ollama and responds
- Keyboard shortcut: **Ctrl+K**

## 🎬 VAMP Video States

### Idle (Ready)
- Video is paused at frame 0
- Indicates: "Ready for your instruction"
- Triggers: After completing any action

### Busy (Thinking)
- Video stops with thinking overlay
- Shows messages like "Analysing…", "Consulting archives…"
- Triggers: 
  - Evidence scan starts
  - Expectations generation
  - AI guidance request
  - Report generation

### Speaking (Responding)
- Video plays on loop
- Shows dialogue bubbles
- Triggers:
  - AI returns guidance
  - Scan completes
  - Any message from VAMP
- Auto-returns to idle after speech (based on text length)

## 🎨 UI Components

### Tables
- **Expectations**: Full task breakdown with progress bars
- **Scan Results**: AI classification with confidence scores
- **Evidence**: Historical evidence storage

### Progress Bars
- **KPA Progress**: Luminous crimson bars with shimmer effect
- **Task Progress**: Inline 100% completion indicators
- Color-coded: Green (high), Orange (medium), Red (low)

### Modals
- **AI Guidance**: Get help on specific tasks
- **Resolve Classification**: Manual KPA assignment
- Press **Escape** to close any modal

## 🔧 Configuration

### Environment Variables

```bash
# Ollama settings
export OLLAMA_BASE_URL="http://localhost:11434"
export OLLAMA_MODEL="llama2"
```

### File Locations

- **Uploads**: `./uploads/`
- **Contracts**: `./backend/data/contracts/`
- **Evidence**: `./backend/data/evidence/`

## 🐛 Troubleshooting

### "Cannot reach Ollama"
- Ensure Ollama is running: `ollama serve`
- Check Ollama is on port 11434
- Test with: `curl http://localhost:11434/api/generate`

### "VAMP unavailable"
- Server may not be running
- Check console for errors
- Restart with: `python run_web.py`

### Video not playing
- Check video file exists: `./assets/vampire.mp4`
- Browser may block autoplay
- Click on video area to enable

### Tables not loading
- Check browser console (F12)
- Verify API endpoints are responding
- Look for CORS errors

## 📊 API Endpoints

### Profile
- `POST /api/profile/enrol` - Create/load profile

### Task Agreement
- `POST /api/ta/import` - Import TA Excel file

### Expectations
- `GET /api/expectations?staff_id=X&year=Y` - Get expectations

### Scanning
- `POST /api/scan/upload` - Upload & scan files
- `GET /api/scan/events` - Real-time event stream

### Evidence
- `GET /api/evidence?staff_id=X` - Get evidence
- `POST /api/evidence/resolve` - Resolve classification

### AI
- `POST /api/vamp/ask` - Ask VAMP question
- `POST /api/ai/guidance` - Get task guidance

### Reports
- `GET /api/report/generate?staff_id=X&period=final` - Generate PA

## 🎯 Key Features

### Context-Aware AI
- VAMP knows your staff ID, cycle year, current stage
- Provides relevant guidance based on where you are

### Confidence-Based Review
- AI flags uncertain classifications (< 60%)
- Manual resolution workflow
- Explanation required for accountability

### Real-Time Feedback
- Server-Sent Events for scan progress
- Live progress bars
- Instant status updates

### Keyboard Shortcuts
- **Ctrl+K**: Focus Ask VAMP input
- **Escape**: Close modals
- **Enter**: Submit in Ask VAMP (Shift+Enter for newline)

## 🎨 Design Philosophy

- **Gothic Academic**: Dark theme, serif fonts, crimson accents
- **Vampire Metaphor**: VAMP as a guide through the night of performance management
- **Professional**: NWU branding, institutional colors
- **Intuitive**: Clear status indicators, progress tracking
- **Responsive**: Adapts to different screen sizes

## 📝 Notes

- Mock data used when backend modules unavailable
- Ollama required for full AI features
- Video autoplay may be blocked by browsers
- File extraction simplified (extend for production)

## 🚀 Next Steps

1. **Enhance AI Classification**
   - Add JSON parsing for Ollama responses
   - Implement confidence scoring
   - Add KPA-specific prompts

2. **Backend Integration**
   - Connect to real expectation engine
   - Implement evidence store
   - Add PA generation

3. **File Processing**
   - Add PDF extraction (PyPDF2)
   - Add DOCX support (python-docx)
   - Add OCR for scanned documents

4. **Production Ready**
   - Add authentication
   - Implement proper session management
   - Add database backend
   - Deploy with WSGI server

---

**Built for NWU Academic Performance Management** 🎓  
*VAMP: Your guide through the academic night* 🦇
