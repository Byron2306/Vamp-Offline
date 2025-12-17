# 🎙️ VAMP Voice Cloning - Quick Start

## What is This?

VAMP can now **speak** to you using a cloned voice! Using OpenVoice V2 (MIT License), you can train VAMP to use any voice from just 3-5 audio samples.

## Quick Setup (5 Minutes)

### 1. Install Dependencies

**Linux/Mac:**
```bash
./setup_voice.sh
```

**Windows:**
```powershell
.\setup_voice_windows.ps1
```

**Or manually:**
```bash
# Install PyTorch first
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu

# Install audio libraries
pip install soundfile scipy librosa pydub

# Install OpenVoice (may require FFmpeg)
pip install git+https://github.com/myshell-ai/OpenVoice.git
```

**Windows users**: If installation fails, see [VOICE_WINDOWS_SETUP.md](VOICE_WINDOWS_SETUP.md)

### 2. Prepare Voice Samples

You need 3-5 audio files:
- **Duration**: 5-30 seconds each
- **Format**: WAV, MP3, FLAC, M4A, or OGG
- **Quality**: Clear speech, no background noise
- **Content**: Any natural speech (reading, conversation, etc.)

Place them in: `data/voice_samples/`

### 3. Train Voice (Web UI)

1. Start VAMP:
   ```bash
   python run_web.py
   ```

2. Open: http://localhost:5000

3. Go to **Voice Settings** tab

4. Upload your voice samples

5. Click **Train Voice Model** (takes 1-5 minutes)

6. Test it with **Generate Test Speech**

### 4. Use It!

Now when you ask VAMP questions, it will respond with voice!

Type your question in "Ask VAMP" → VAMP responds with text AND voice 🔊

## Test Installation

```bash
python test_voice.py
```

This checks if everything is installed correctly.

## Example Voice Samples

Good voice samples:
- ✅ Reading a paragraph from a book
- ✅ Answering questions naturally
- ✅ Explaining a concept
- ✅ Different emotions/tones

Bad voice samples:
- ❌ Background music or noise
- ❌ Multiple speakers
- ❌ Very short clips (< 5 seconds)
- ❌ Poor audio quality

## Troubleshooting

### "Voice cloning not available"
```bash
pip install torch torchaudio soundfile scipy
pip install git+https://github.com/myshell-ai/OpenVoice.git
```

### "No training files found"
Place audio files in `data/voice_samples/` first

### Slow training/synthesis
- Use GPU if available (much faster)
- Reduce sample length if needed
- Close other applications

## System Requirements

**Minimum:**
- Python 3.8+
- 4GB RAM
- 2GB disk space

**Recommended:**
- Python 3.10+
- 8GB RAM
- NVIDIA GPU with 4GB+ VRAM
- 5GB disk space

## Privacy

✅ **100% local processing** - nothing is sent to the cloud
✅ **Your voice samples stay on your machine**
✅ **No external API dependencies**

## License

OpenVoice V2: MIT License - https://github.com/myshell-ai/OpenVoice

## Need Help?

1. Read the full guide: [VOICE_CLONING_GUIDE.md](VOICE_CLONING_GUIDE.md)
2. Check the logs in the web interface
3. Run test script: `python test_voice.py`

## Architecture

```
Your Question
    ↓
Ollama (generates text)
    ↓
OpenVoice V2 (generates speech)
    ↓
Browser plays audio 🔊
```

---

**Ready?** Run `./setup_voice.sh` and start training! 🎉
