# PowerShell script for Windows voice setup
# Run this as: .\setup_voice_windows.ps1

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "VAMP Voice Cloning Setup - Windows" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# Check Python version
Write-Host "Checking Python version..." -ForegroundColor Yellow
$pythonVersion = python --version 2>&1
Write-Host "Found: $pythonVersion" -ForegroundColor Green

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Python not found. Please install Python 3.8+ first." -ForegroundColor Red
    exit 1
}

# Check if pip is available
Write-Host ""
Write-Host "Checking pip..." -ForegroundColor Yellow
$pipVersion = pip --version 2>&1
Write-Host "Found: $pipVersion" -ForegroundColor Green

# Upgrade pip
Write-Host ""
Write-Host "Upgrading pip..." -ForegroundColor Yellow
python -m pip install --upgrade pip

# Install PyTorch
Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "Step 1: Installing PyTorch" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Choose PyTorch version:" -ForegroundColor Yellow
Write-Host "  1. CPU only (smaller, works on any PC)"
Write-Host "  2. CUDA 11.8 (for NVIDIA GPUs)"
Write-Host "  3. CUDA 12.1 (for newer NVIDIA GPUs)"
Write-Host "  4. Skip (already installed)"
$choice = Read-Host "Enter choice (1-4)"

switch ($choice) {
    "1" {
        Write-Host "Installing PyTorch (CPU)..." -ForegroundColor Yellow
        pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
    }
    "2" {
        Write-Host "Installing PyTorch (CUDA 11.8)..." -ForegroundColor Yellow
        pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu118
    }
    "3" {
        Write-Host "Installing PyTorch (CUDA 12.1)..." -ForegroundColor Yellow
        pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
    }
    "4" {
        Write-Host "Skipping PyTorch installation" -ForegroundColor Yellow
    }
    default {
        Write-Host "Invalid choice. Installing CPU version..." -ForegroundColor Yellow
        pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
    }
}

# Check FFmpeg
Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "Step 2: Checking FFmpeg" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

$ffmpegInstalled = Get-Command ffmpeg -ErrorAction SilentlyContinue

if ($ffmpegInstalled) {
    Write-Host "✓ FFmpeg is already installed" -ForegroundColor Green
    ffmpeg -version | Select-Object -First 1
} else {
    Write-Host "✗ FFmpeg not found" -ForegroundColor Red
    Write-Host ""
    Write-Host "FFmpeg is required for audio processing." -ForegroundColor Yellow
    Write-Host "Options to install FFmpeg:" -ForegroundColor Yellow
    Write-Host "  1. Using Chocolatey: choco install ffmpeg"
    Write-Host "  2. Download from: https://ffmpeg.org/download.html"
    Write-Host "  3. Using conda: conda install -c conda-forge ffmpeg"
    Write-Host ""
    Write-Host "Would you like to try installing with Chocolatey? (y/n)"
    $installFFmpeg = Read-Host
    
    if ($installFFmpeg -eq "y") {
        Write-Host "Installing FFmpeg with Chocolatey..." -ForegroundColor Yellow
        choco install ffmpeg -y
    } else {
        Write-Host "Please install FFmpeg manually and run this script again." -ForegroundColor Yellow
    }
}

# Install audio libraries
Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "Step 3: Installing Audio Libraries" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

pip install soundfile scipy librosa pydub

# Try installing OpenVoice
Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "Step 4: Installing OpenVoice V2" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "Attempting to install OpenVoice..." -ForegroundColor Yellow
Write-Host "(This may fail on 'av' package - that's okay)" -ForegroundColor Yellow
Write-Host ""

# Try full install first
pip install git+https://github.com/myshell-ai/OpenVoice.git

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Full install failed. Trying without dependencies..." -ForegroundColor Yellow
    pip install --no-deps git+https://github.com/myshell-ai/OpenVoice.git
    
    # Install other dependencies
    pip install onnxruntime pydub audioseal
}

# Download models
Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "Step 5: Downloading OpenVoice Models" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

$modelsDir = "models\openvoice_v2"

if (Test-Path $modelsDir) {
    Write-Host "Models directory already exists: $modelsDir" -ForegroundColor Yellow
    Write-Host "Would you like to re-download? (y/n)"
    $redownload = Read-Host
    
    if ($redownload -ne "y") {
        Write-Host "Skipping model download" -ForegroundColor Yellow
    } else {
        Remove-Item -Recurse -Force $modelsDir
        New-Item -ItemType Directory -Path $modelsDir
    }
} else {
    New-Item -ItemType Directory -Path $modelsDir -Force
}

if (-not (Test-Path "$modelsDir\base_speakers")) {
    Write-Host "Downloading models (this may take a few minutes)..." -ForegroundColor Yellow
    
    # Check if git is available
    $gitInstalled = Get-Command git -ErrorAction SilentlyContinue
    
    if ($gitInstalled) {
        git clone https://huggingface.co/myshell-ai/OpenVoiceV2 "$modelsDir\temp_download"
        
        if (Test-Path "$modelsDir\temp_download\base_speakers") {
            Move-Item "$modelsDir\temp_download\base_speakers" $modelsDir
            Move-Item "$modelsDir\temp_download\converter" $modelsDir
            Remove-Item -Recurse -Force "$modelsDir\temp_download"
            Write-Host "✓ Models downloaded successfully" -ForegroundColor Green
        } else {
            Write-Host "✗ Model download failed" -ForegroundColor Red
        }
    } else {
        Write-Host "✗ Git not found. Please install git and run this script again." -ForegroundColor Red
        Write-Host "Or download models manually from: https://huggingface.co/myshell-ai/OpenVoiceV2" -ForegroundColor Yellow
    }
}

# Create directories
Write-Host ""
Write-Host "Creating data directories..." -ForegroundColor Yellow
New-Item -ItemType Directory -Path "data\voice_samples" -Force | Out-Null
New-Item -ItemType Directory -Path "cache\voice" -Force | Out-Null

# Run test
Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "Step 6: Testing Installation" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

python test_voice.py

# Final instructions
Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "Setup Complete!" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. Place your voice samples (3-5 audio files) in: data\voice_samples\"
Write-Host "  2. Start VAMP: python run_web.py"
Write-Host "  3. Open: http://localhost:5000"
Write-Host "  4. Go to 'Voice Settings' tab"
Write-Host "  5. Train your voice model"
Write-Host ""
Write-Host "If you encountered errors, check:" -ForegroundColor Yellow
Write-Host "  - VOICE_WINDOWS_SETUP.md (troubleshooting guide)"
Write-Host "  - VOICE_CLONING_GUIDE.md (full documentation)"
Write-Host ""
Write-Host "Press any key to exit..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
