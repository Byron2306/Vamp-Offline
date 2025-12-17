#!/usr/bin/env python3
"""
Quick test script for VAMP voice cloning functionality
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

def test_imports():
    """Test that all required imports work"""
    print("Testing imports...")
    
    try:
        import torch
        print(f"✓ torch: {torch.__version__}")
    except ImportError as e:
        print(f"✗ torch: {e}")
        return False
    
    try:
        import torchaudio
        print(f"✓ torchaudio: {torchaudio.__version__}")
    except ImportError as e:
        print(f"✗ torchaudio: {e}")
        return False
    
    try:
        import soundfile
        print(f"✓ soundfile: {soundfile.__version__}")
    except ImportError as e:
        print(f"✗ soundfile: {e}")
        return False
    
    try:
        import scipy
        print(f"✓ scipy: {scipy.__version__}")
    except ImportError as e:
        print(f"✗ scipy: {e}")
        return False
    
    try:
        from openvoice import se_extractor
        from openvoice.api import ToneColorConverter, BaseSpeakerTTS
        print(f"✓ OpenVoice V2")
    except ImportError as e:
        print(f"✗ OpenVoice V2: {e}")
        return False
    
    return True


def test_voice_cloner():
    """Test voice cloner initialization"""
    print("\nTesting voice cloner...")
    
    try:
        from backend.llm.voice_cloner import VoiceCloner
        
        cloner = VoiceCloner()
        status = cloner.status()
        
        print(f"✓ VoiceCloner initialized")
        print(f"  - Device: {status['device']}")
        print(f"  - OpenVoice available: {status['openvoice_available']}")
        print(f"  - Audio libs available: {status['audio_libs_available']}")
        print(f"  - Is trained: {status['is_trained']}")
        print(f"  - Training files available: {status['training_files_available']}")
        print(f"  - Model dir: {status['model_dir']}")
        print(f"  - Cache dir: {status['cache_dir']}")
        print(f"  - Training dir: {status['training_dir']}")
        
        return True
        
    except Exception as e:
        print(f"✗ VoiceCloner error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_directories():
    """Test that required directories exist"""
    print("\nTesting directories...")
    
    dirs = [
        project_root / "models" / "openvoice_v2",
        project_root / "cache" / "voice",
        project_root / "data" / "voice_samples",
    ]
    
    all_exist = True
    for d in dirs:
        if d.exists():
            print(f"✓ {d.relative_to(project_root)}")
        else:
            print(f"✗ {d.relative_to(project_root)} (missing)")
            all_exist = False
    
    return all_exist


def main():
    print("=" * 60)
    print("VAMP Voice Cloning Test")
    print("=" * 60)
    print()
    
    # Test imports
    if not test_imports():
        print("\n❌ Import test failed!")
        print("Run: pip install torch torchaudio soundfile scipy")
        print("     pip install git+https://github.com/myshell-ai/OpenVoice.git")
        return 1
    
    # Test directories
    if not test_directories():
        print("\n⚠️  Some directories missing (will be created automatically)")
    
    # Test voice cloner
    if not test_voice_cloner():
        print("\n❌ Voice cloner test failed!")
        return 1
    
    print("\n" + "=" * 60)
    print("✅ All tests passed!")
    print("=" * 60)
    print()
    print("Next steps:")
    print("1. Place voice samples in: data/voice_samples/")
    print("2. Start web server: python run_web.py")
    print("3. Open: http://localhost:5000")
    print("4. Go to 'Voice Settings' tab")
    print("5. Train your voice model")
    print()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
