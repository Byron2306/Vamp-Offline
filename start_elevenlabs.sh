#!/bin/bash
# Quick start script for VAMP with ElevenLabs TTS

echo "========================================"
echo "VAMP - ElevenLabs TTS Quick Start"
echo "========================================"
echo ""

# Check if Ollama is running
echo "Checking Ollama service..."
if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "✓ Ollama is running"
else
    echo "⚠ Ollama is not running"
    echo "  Start it with: ollama serve"
    echo ""
fi

# Check if llama3.2:3b model is available
echo ""
echo "Checking Ollama model..."
if ollama list | grep -q "llama3.2:3b"; then
    echo "✓ llama3.2:3b model is available"
else
    echo "⚠ llama3.2:3b model not found"
    echo "  Pulling model (this may take a few minutes)..."
    ollama pull llama3.2:3b
fi

# Check Python dependencies
echo ""
echo "Checking Python dependencies..."
if python -c "import elevenlabs" 2>/dev/null; then
    echo "✓ elevenlabs package installed"
else
    echo "⚠ elevenlabs package not found"
    echo "  Installing..."
    pip install elevenlabs
fi

# Test ElevenLabs connection
echo ""
echo "Testing ElevenLabs API connection..."
python -c "
from backend.llm.elevenlabs_tts import get_tts_client
client = get_tts_client()
quota = client.check_quota()
if quota:
    print('✓ ElevenLabs API is working')
    print(f'  Characters remaining: {quota[\"character_limit\"] - quota[\"character_count\"]}')
else:
    print('⚠ Could not connect to ElevenLabs API')
" 2>/dev/null

echo ""
echo "========================================"
echo "Ready to start!"
echo "========================================"
echo ""
echo "To start the VAMP web server:"
echo "  python run_web.py"
echo ""
echo "To test the integration:"
echo "  python test_elevenlabs.py"
echo ""
echo "Web interface will be available at:"
echo "  http://localhost:5000"
echo ""
