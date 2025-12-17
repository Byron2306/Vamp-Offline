#!/bin/bash
# VAMP Voice Setup Script
# Sets up OpenVoice V2 for voice cloning functionality

set -e

echo "========================================"
echo "VAMP Voice Cloning Setup (OpenVoice V2)"
echo "========================================"
echo ""

# Check Python version
echo "Checking Python version..."
python3 --version

# Create directories
echo ""
echo "Creating directories..."
mkdir -p models/openvoice_v2
mkdir -p data/voice_samples
mkdir -p cache/voice

# Install dependencies
echo ""
echo "Installing Python dependencies..."
pip install torch torchaudio soundfile scipy

# Install OpenVoice V2 from GitHub
echo ""
echo "Installing OpenVoice V2..."
pip install git+https://github.com/myshell-ai/OpenVoice.git

# Download OpenVoice V2 models
echo ""
echo "Downloading OpenVoice V2 models..."
echo "This will download the pre-trained models (~500MB)"
echo ""

cd models/openvoice_v2

# Download base speakers and converter models
if [ ! -d "base_speakers" ]; then
    echo "Downloading base speakers..."
    git clone https://huggingface.co/myshell-ai/OpenVoiceV2 temp_download
    mv temp_download/base_speakers ./
    mv temp_download/converter ./
    rm -rf temp_download
    echo "✓ Models downloaded"
else
    echo "✓ Models already exist"
fi

cd ../..

echo ""
echo "========================================"
echo "✓ Voice setup complete!"
echo "========================================"
echo ""
echo "Next steps:"
echo "1. Start the VAMP web server: python run_web.py"
echo "2. Open http://localhost:5000 in your browser"
echo "3. Go to the 'Voice Settings' tab"
echo "4. Upload 3-5 voice samples (5-30 seconds each)"
echo "5. Click 'Train Voice Model'"
echo "6. Test with 'Generate Test Speech'"
echo "7. Ask VAMP questions - it will respond with voice!"
echo ""
echo "Voice samples should be:"
echo "  • Clear, high-quality recordings"
echo "  • 5-30 seconds of continuous speech"
echo "  • WAV, MP3, or FLAC format"
echo "  • From the voice you want to clone"
echo ""
