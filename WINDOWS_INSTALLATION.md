# VAMP Voice Cloning - Windows Installation Guide

## ⚠️ Important: Python Version

**Python 3.14 is NOT compatible** with the required packages. You need **Python 3.11** or **Python 3.12**.

## Step-by-Step Windows Installation

### 1. Install Python 3.11

1. Download Python 3.11 from: https://www.python.org/downloads/
2. During installation, check "Add Python to PATH"
3. Verify installation:
   ```cmd
   py -3.11 --version
   ```

### 2. Create Virtual Environment

```cmd
cd path\to\Vamp-Offline
py -3.11 -m venv venv
venv\Scripts\activate
```

You should see `(venv)` in your command prompt.

### 3. Upgrade pip

```cmd
python -m pip install --upgrade pip setuptools wheel
```

### 4. Install Core Dependencies

```cmd
pip install -r requirements-windows.txt
```

### 5. Install PyTorch (CPU version for Windows)

```cmd
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
```

**Note**: If you have NVIDIA GPU, use CUDA version instead:
```cmd
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu118
```

### 6. Install OpenVoice V2

```cmd
pip install git+https://github.com/myshell-ai/OpenVoice.git
```

If this fails, try:
```cmd
git clone https://github.com/myshell-ai/OpenVoice.git
cd OpenVoice
pip install -e .
cd ..
```

### 7. Verify Installation

```cmd
python test_voice.py
```

If you see "✅ All tests passed!" - you're ready!

## Common Windows Issues

### Issue: "torch" not found
**Solution**: Install PyTorch separately before other packages:
```cmd
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
```

### Issue: Git not installed
**Solution**: Install Git from https://git-scm.com/download/win
Or use ZIP download method:
1. Download OpenVoice as ZIP from GitHub
2. Extract and install manually

### Issue: Visual C++ build tools required
**Solution**: Install Microsoft C++ Build Tools:
https://visualstudio.microsoft.com/visual-cpp-build-tools/

Select "Desktop development with C++" during installation.

### Issue: "Cannot import mesonpy"
**Solution**: This means you're using Python 3.14. Downgrade to Python 3.11.

## Quick Install Script (PowerShell)

Save this as `install_voice.ps1`:

```powershell
# VAMP Voice Installation Script for Windows

Write-Host "VAMP Voice Cloning Setup" -ForegroundColor Cyan

# Check Python version
$pythonVersion = py -3.11 --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Python 3.11 not found!" -ForegroundColor Red
    Write-Host "Download from: https://www.python.org/downloads/" -ForegroundColor Yellow
    exit 1
}

Write-Host "✓ Python 3.11 found" -ForegroundColor Green

# Create virtual environment
Write-Host "Creating virtual environment..." -ForegroundColor Yellow
py -3.11 -m venv venv
.\venv\Scripts\Activate.ps1

# Upgrade pip
Write-Host "Upgrading pip..." -ForegroundColor Yellow
python -m pip install --upgrade pip setuptools wheel

# Install core dependencies
Write-Host "Installing core dependencies..." -ForegroundColor Yellow
pip install -r requirements-windows.txt

# Install PyTorch
Write-Host "Installing PyTorch (CPU version)..." -ForegroundColor Yellow
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu

# Install OpenVoice
Write-Host "Installing OpenVoice V2..." -ForegroundColor Yellow
pip install git+https://github.com/myshell-ai/OpenVoice.git

# Test installation
Write-Host "Testing installation..." -ForegroundColor Yellow
python test_voice.py

Write-Host "`n✓ Installation complete!" -ForegroundColor Green
Write-Host "Run: python run_web.py" -ForegroundColor Cyan
```

Run with:
```cmd
powershell -ExecutionPolicy Bypass -File install_voice.ps1
```

## Manual Installation (No Git)

If you don't have Git installed:

1. Install core dependencies:
   ```cmd
   pip install -r requirements-windows.txt
   ```

2. Download PyTorch wheels:
   - Visit: https://download.pytorch.org/whl/cpu/torch/
   - Download appropriate `.whl` files
   - Install: `pip install torch-*.whl`

3. Download OpenVoice:
   - Visit: https://github.com/myshell-ai/OpenVoice
   - Click "Code" → "Download ZIP"
   - Extract and run: `pip install .` inside the folder

## After Installation

1. Place voice samples in `data\voice_samples\`
2. Start VAMP: `python run_web.py`
3. Open: http://localhost:5000
4. Go to "Voice Settings" tab
5. Upload samples and train!

## System Requirements

- Windows 10/11
- Python 3.11 or 3.12 (NOT 3.14)
- 4GB RAM minimum (8GB recommended)
- 2GB free disk space
- Optional: NVIDIA GPU with CUDA support

## Need Help?

1. Make sure you're using Python 3.11 or 3.12
2. Check all error messages carefully
3. Try installing in a fresh virtual environment
4. Ensure Visual C++ Build Tools are installed

## Quick Troubleshooting

| Error | Solution |
|-------|----------|
| Python 3.14 | Downgrade to 3.11 |
| Cannot import mesonpy | Use Python 3.11 |
| ImpImporter error | Upgrade pip: `python -m pip install --upgrade pip` |
| torch not found | Install separately: `pip install torch torchaudio` |
| Git not found | Install Git or download ZIP manually |

---

**TIP**: Always use Python 3.11 for best compatibility with AI/ML packages!
