# 🎙️ VAMP Voice Cloning - Setup Checklist

Use this checklist to set up and verify your VAMP voice cloning installation.

## 📋 Pre-Installation Checklist

- [ ] Python 3.8+ installed
- [ ] pip package manager working
- [ ] At least 2GB free disk space
- [ ] Internet connection (for initial download)

### Recommended (Optional)
- [ ] NVIDIA GPU with CUDA support (for faster processing)
- [ ] 4GB+ RAM available
- [ ] High-quality microphone (if recording your own samples)

## 🔧 Installation Checklist

### Step 1: Install Dependencies

- [ ] Run `./setup_voice.sh` OR
- [ ] Manual installation:
  - [ ] `pip install torch torchaudio`
  - [ ] `pip install soundfile scipy`
  - [ ] `pip install git+https://github.com/myshell-ai/OpenVoice.git`

### Step 2: Download Models

- [ ] Models directory created: `models/openvoice_v2/`
- [ ] Base speakers downloaded (~300MB)
- [ ] Tone converter downloaded (~200MB)
- [ ] Total size: ~500MB

### Step 3: Create Directories

- [ ] `data/voice_samples/` exists
- [ ] `cache/voice/` exists
- [ ] `models/openvoice_v2/` exists

### Step 4: Test Installation

- [ ] Run `python test_voice.py`
- [ ] All imports successful
- [ ] Voice cloner loads
- [ ] No errors in output

## 🎤 Voice Sample Preparation Checklist

### Sample Requirements

- [ ] Have 3-5 audio files ready
- [ ] Each file is 5-30 seconds long
- [ ] Files are in WAV, MP3, or FLAC format
- [ ] Audio is clear (no background noise)
- [ ] Sample rate is 44.1kHz or higher (recommended)

### Sample Quality Check

- [ ] Voice is clearly audible
- [ ] No music or sound effects
- [ ] Single speaker only
- [ ] Natural speech (not robotic)
- [ ] Good recording quality
- [ ] Varied emotion/pitch across samples

### Where to Place Samples

- [ ] Samples copied to `data/voice_samples/`
- [ ] Files have reasonable names (e.g., `sample1.wav`)
- [ ] No spaces in filenames (use underscores)

## 🌐 Web Interface Setup Checklist

### Step 1: Start Server

- [ ] Run `python run_web.py`
- [ ] Server starts without errors
- [ ] See "Server running at: http://localhost:5000"

### Step 2: Open Browser

- [ ] Open http://localhost:5000
- [ ] Page loads successfully
- [ ] VAMP interface visible
- [ ] No console errors (F12 to check)

### Step 3: Check Voice Status

- [ ] Click "Voice Settings" tab
- [ ] Voice status box shows information
- [ ] No "not available" errors
- [ ] Device shown (cuda or cpu)

## 🎯 Training Checklist

### Upload Samples

- [ ] Click "Choose Files" button
- [ ] Select 3-5 voice samples
- [ ] Click "Upload Voice Sample(s)"
- [ ] See success message for each file
- [ ] "Training files available" count increases

### Train Voice Model

- [ ] Click "Train Voice Model" button
- [ ] Training starts (may take 1-15 minutes)
- [ ] Progress message shown
- [ ] Training completes successfully
- [ ] Success message appears with details

### Verify Training

- [ ] Voice status shows "Voice model trained and ready"
- [ ] Embedding file exists: `cache/voice/vamp_voice_embedding.pt`
- [ ] Config file exists: `cache/voice/voice_config.json`
- [ ] "Is trained" shows as true

## 🔊 Testing Checklist

### Test Speech Generation

- [ ] Go to "Voice Settings" tab
- [ ] Find "Test Voice" section
- [ ] Enter test text (or use default)
- [ ] Click "Generate Test Speech"
- [ ] Audio player appears
- [ ] Click play button
- [ ] Hear voice speaking the text
- [ ] Voice sounds natural

### Test in Chat

- [ ] Go to any other tab (e.g., Enrolment)
- [ ] Find "Ask VAMP" input at top
- [ ] Type a question: "Hello VAMP, can you hear me?"
- [ ] Click "Ask VAMP" button
- [ ] Text response appears in bubble
- [ ] Audio plays automatically
- [ ] Voice sounds like your samples

## ✅ Verification Checklist

### Functionality Tests

- [ ] Voice status API works: `curl http://localhost:5000/api/voice/status`
- [ ] Can upload new samples
- [ ] Can retrain voice if needed
- [ ] Can generate test speech
- [ ] VAMP responds with voice in chat
- [ ] Audio plays in browser
- [ ] Can control audio playback (pause/play)

### Performance Tests

- [ ] Training completes in reasonable time (< 15 min)
- [ ] Speech generation happens (< 30 sec per response)
- [ ] No memory errors
- [ ] No disk space issues
- [ ] Browser doesn't freeze during playback

### Quality Tests

- [ ] Voice sounds natural (not robotic)
- [ ] Voice matches your samples
- [ ] Speech is clear and understandable
- [ ] No audio artifacts or glitches
- [ ] Volume is appropriate

## 🐛 Troubleshooting Checklist

If something doesn't work, check:

### Installation Issues

- [ ] Python version is 3.8+: `python --version`
- [ ] PyTorch installed: `python -c "import torch; print(torch.__version__)"`
- [ ] OpenVoice installed: `python -c "import openvoice"`
- [ ] Models downloaded: `ls models/openvoice_v2/`
- [ ] Directories exist: `ls -la data/ cache/`

### Training Issues

- [ ] Voice samples uploaded: `ls data/voice_samples/`
- [ ] At least 3 samples present
- [ ] Samples are valid audio files
- [ ] Enough disk space: `df -h`
- [ ] Enough memory: `free -h`
- [ ] Check logs in web interface

### Playback Issues

- [ ] Browser supports HTML5 audio
- [ ] Browser allows autoplay
- [ ] Audio file generated: `ls cache/voice/`
- [ ] Audio URL is accessible
- [ ] No browser console errors (F12)
- [ ] Volume not muted

### Performance Issues

- [ ] Close other applications
- [ ] Check GPU availability: `nvidia-smi` (if using CUDA)
- [ ] Reduce sample size if needed
- [ ] Use CPU mode if GPU fails
- [ ] Clear old cache files: `rm cache/voice/speech_*.wav`

## 📝 Post-Setup Checklist

### Documentation

- [ ] Read [VOICE_QUICK_START.md](VOICE_QUICK_START.md)
- [ ] Browse [VOICE_CLONING_GUIDE.md](VOICE_CLONING_GUIDE.md)
- [ ] Check [VOICE_ARCHITECTURE.md](VOICE_ARCHITECTURE.md) for details
- [ ] Bookmark for future reference

### Usage Tips

- [ ] Use GPU for faster processing (if available)
- [ ] Keep voice samples for future retraining
- [ ] Clear cache periodically to save space
- [ ] Record more samples for better quality
- [ ] Test different text to verify quality

### Best Practices

- [ ] Only clone voices you have permission to use
- [ ] Use high-quality source audio
- [ ] Keep 3-5 diverse samples
- [ ] Retrain if quality isn't good enough
- [ ] Back up your trained model

## 🎉 Success Criteria

You're done when:

- ✅ All installation steps completed
- ✅ Voice model trained successfully
- ✅ Test speech plays correctly
- ✅ VAMP responds with voice in chat
- ✅ Voice quality is acceptable
- ✅ No errors in logs

## 🚀 Next Steps

After successful setup:

1. **Use it**: Ask VAMP questions and hear responses
2. **Experiment**: Try different voices by retraining
3. **Optimize**: Adjust settings for your hardware
4. **Share**: Show others how cool voice VAMP is!
5. **Feedback**: Report issues or suggestions

---

## Quick Reference

**Start Server**: `python run_web.py`
**Test Installation**: `python test_voice.py`
**Web UI**: http://localhost:5000
**Voice Tab**: Voice Settings
**Training Time**: 1-15 minutes (varies by hardware)
**Sample Location**: `data/voice_samples/`
**Cache Location**: `cache/voice/`

---

**Print this checklist and check off items as you go! 📋✅**
