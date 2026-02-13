#!/bin/bash

echo "======================================"
echo "VAMP Web GUI - Startup Script"
echo "======================================"
echo ""

# Respect LLM provider selection: skip Ollama check if using Groq or GROQ_API_KEY is present
echo "Checking LLM provider..."
LLM_PROVIDER=${LLM_PROVIDER:-$(printenv LLM_PROVIDER || echo "groq")}
GROQ_KEY=$(printenv GROQ_API_KEY || true)
if [ "$LLM_PROVIDER" = "ollama" ] || [ -z "$GROQ_KEY" -a "$LLM_PROVIDER" != "groq" ]; then
    echo "Checking Ollama service..."
    if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo "✓ Ollama is running"
    else
        echo "⚠️  Ollama is not running. Starting Ollama..."
        echo "   Run: ollama serve"
        echo "   Then run this script again."
        exit 1
    fi
else
    echo "Using Groq (cloud) or GROQ_API_KEY present; skipping Ollama check"
fi

echo ""
echo "Starting VAMP Web Server..."
echo "Server will be available at: http://localhost:5000"
echo ""
echo "Press Ctrl+C to stop the server"
echo "======================================"
echo ""

# Check if virtual environment exists
if [ -d ".venv" ]; then
    echo "Using virtual environment (.venv)"
    .venv/bin/python run_web.py
else
    # Fallback to system Python
    python3 run_web.py
fi
