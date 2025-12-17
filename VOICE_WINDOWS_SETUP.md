# 🪟 Voice Cloning Setup - Windows Guide

The OpenVoice package has dependencies that can be tricky to install on Windows. Follow this guide for a smooth setup.

## Problem

The `av` (PyAV) package requires compilation and may fail on Windows with Cython errors.

## Solution

Install dependencies in the correct order and use pre-built wheels where possible.

## Step-by-Step Installation

### Option 1: Quick Install (Recommended)

Run the Windows setup script:

```powershell
.\setup_voice_windows.ps1
```

### Option 2: Manual Installation

Follow these steps in order:

#### 1. Install PyTorch (CPU or CUDA version)

**For CPU only:**
```powershell
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
```

**For NVIDIA GPU (CUDA 11.8):**
```powershell
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu118
```

**For NVIDIA GPU (CUDA 12.1):**
```powershell
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
```

#### 2. Install FFmpeg (Required for audio processing)

**Option A: Using Chocolatey**
```powershell
choco install ffmpeg
```

**Option B: Manual Download**
1. Download FFmpeg from https://ffmpeg.org/download.html#build-windows
2. Extract to `C:\ffmpeg`
3. Add `C:\ffmpeg\bin` to your PATH

**Option C: Using Conda**
```powershell
conda install -c conda-forge ffmpeg
```

#### 3. Install Audio Libraries

```powershell
pip install soundfile scipy librosa pydub
```

#### 4. Install OpenVoice (Skip PyAV if it fails)

```powershell
# Try installing OpenVoice
pip install git+https://github.com/myshell-ai/OpenVoice.git

# If it fails on 'av' package, skip it:
pip install --no-deps git+https://github.com/myshell-ai/OpenVoice.git

# Then install other dependencies manually:
pip install onnxruntime pydub audioseal
```

#### 5. Download OpenVoice Models

```powershell
# Create models directory
mkdir models\openvoice_v2

# Download base speakers
git clone https://huggingface.co/myshell-ai/OpenVoiceV2 models\openvoice_v2\temp_download

# Move required files
move models\openvoice_v2\temp_download\base_speakers models\openvoice_v2\
move models\openvoice_v2\temp_download\converter models\openvoice_v2\

# Clean up
rmdir /s /q models\openvoice_v2\temp_download
```

### Option 3: Using Pre-built Wheels (If available)

Check for pre-built wheels at https://www.lfd.uci.edu/~gohlke/pythonlibs/

Download and install:
```powershell
pip install path\to\downloaded\package.whl
```

## Troubleshooting

### Issue: "av" package fails to compile

**Solution 1**: Skip the av package (faster-whisper dependency)
```powershell
# Install OpenVoice without dependencies
pip install --no-deps git+https://github.com/myshell-ai/OpenVoice.git

# Install required deps manually (skip av)
pip install onnxruntime pydub audioseal
```

**Solution 2**: Use a Linux subsystem (WSL2)
```powershell
# Install WSL2
wsl --install

# Use Ubuntu in WSL2
wsl

# Follow Linux installation instructions
./setup_voice.sh
```

**Solution 3**: Use Docker
```powershell
# Pull the VAMP Docker image (when available)
docker pull vamp-offline:latest
docker run -p 5000:5000 vamp-offline
```

### Issue: FFmpeg not found

**Check if FFmpeg is installed:**
```powershell
ffmpeg -version
```

**If not found, install using one of the methods in Step 2 above.**

### Issue: CUDA out of memory

**Use CPU mode:**
1. Set environment variable:
   ```powershell
   $env:VAMP_VOICE_DEVICE="cpu"
   ```

2. Or edit `backend/llm/voice_cloner.py`:
   ```python
   self.device = "cpu"  # Force CPU
   ```

### Issue: Import errors

**Verify installations:**
```powershell
python -c "import torch; print(torch.__version__)"
python -c "import torchaudio; print(torchaudio.__version__)"
python -c "import soundfile; print(soundfile.__version__)"
python -c "import librosa; print(librosa.__version__)"
```

## Simplified Alternative: Use TTS Without Voice Cloning

If OpenVoice installation is too complex, you can use simpler TTS:

### Option: pyttsx3 (Offline, Simple)

```powershell
pip install pyttsx3
```

Edit `backend/llm/voice_cloner.py` to use pyttsx3 instead of OpenVoice.

### Option: gTTS (Online, Google TTS)

```powershell
pip install gTTS
```

Note: Requires internet connection.

## Verify Installation

```powershell
# Run test script
python test_voice.py
```

If all tests pass, you're ready to use voice cloning!

## Quick Start After Installation

1. Start VAMP:
   ```powershell
   python run_web.py
   ```

2. Open browser: http://localhost:5000

3. Go to "Voice Settings" tab

4. Upload 3-5 voice samples (WAV/MP3 files)

5. Click "Train Voice Model"

6. Wait 1-15 minutes (depending on hardware)

7. Ask VAMP a question and hear the voice!

## System Requirements

**Minimum:**
- Windows 10/11
- Python 3.8+
- 4GB RAM
- 5GB disk space

**Recommended:**
- Windows 10/11
- Python 3.10+
- NVIDIA GPU with 4GB+ VRAM
- 8GB RAM
- 10GB disk space

## Alternative: Cloud Installation

If local installation is problematic, consider:

1. **Google Colab**: Run VAMP in a Jupyter notebook
2. **GitHub Codespaces**: Use cloud development environment
3. **AWS/Azure**: Deploy on cloud VM with pre-installed dependencies

## Getting Help

If you continue to have issues:

1. Check the error messages carefully
2. Search for the specific error online
3. Try the WSL2 approach (easier than Windows native)
4. Ask for help with the exact error message

## Summary

**Easiest Path for Windows:**

1. Install PyTorch from official site
2. Install FFmpeg via Chocolatey
3. Skip OpenVoice initially, use basic VAMP
4. Or use WSL2 for Linux-based installation

**Most Reliable Path:**

Use WSL2 (Windows Subsystem for Linux) and follow the Linux installation guide.

---

**Need more help?** Check [VOICE_CLONING_GUIDE.md](VOICE_CLONING_GUIDE.md) or the main [README.md](README.md)
