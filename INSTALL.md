# VAMP Web GUI - Installation Guide

## Quick Install

### 1. Install Python Dependencies

```bash
# Using pip
pip install -r requirements.txt
```

Or if using the virtual environment:

```bash
# Create virtual environment (first time only)
python3 -m venv .venv

# Activate virtual environment
source .venv/bin/activate  # Linux/Mac
# or
.venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt
```

### 2. Install and Start Ollama

```bash
# Install Ollama (if not already installed)
curl https://ollama.ai/install.sh | sh

# Pull a model
ollama pull llama2

# Start Ollama service (in separate terminal)
ollama serve
```

### 3. Start VAMP Web Server

```bash
# Make script executable
chmod +x start_web.sh

# Run the server
./start_web.sh
```

Or manually:

```bash
python3 run_web.py
```

The server will start on **http://localhost:5000**

## Dependencies

### Required
- Flask >= 3.0.0 (Web framework)
- Flask-CORS >= 4.0.0 (Cross-origin resource sharing)
- Werkzeug >= 3.0.0 (WSGI utilities)
- PyPDF2 >= 3.0.0 (PDF processing)
- requests >= 2.31.0 (HTTP library)
- openpyxl >= 3.1.0 (Excel file handling)
- pandas >= 2.0.0 (Data manipulation)

### Optional
- Ollama (LLM for AI features)
- python-docx (DOCX file processing)
- python-pptx (PPTX file processing)

## Troubleshooting

### "No module named flask"
Run: `pip install -r requirements.txt`

### "Cannot reach Ollama"
Ensure Ollama is running: `ollama serve`

### Permission denied on start_web.sh
Run: `chmod +x start_web.sh`

## System Requirements

- Python 3.8 or higher
- 2GB RAM minimum
- Modern web browser (Chrome, Firefox, Edge, Safari)
- Ollama for AI features (optional but recommended)
