"""
OpenVoice V2 Voice Cloning Module for VAMP
MIT License - https://github.com/myshell-ai/OpenVoice

This module provides voice cloning functionality using OpenVoice V2,
allowing VAMP to speak responses using a cloned voice.
"""

import os
import json
import time
import torch
import numpy as np
from pathlib import Path
from typing import Optional, Dict, Any, List
import hashlib
from scipy import signal

# Will be installed via requirements
try:
    from openvoice import se_extractor
    from openvoice.api import ToneColorConverter, BaseSpeakerTTS
    OPENVOICE_AVAILABLE = True
except ImportError as e:
    OPENVOICE_AVAILABLE = False
    OPENVOICE_IMPORT_ERROR = str(e)
    se_extractor = None
    ToneColorConverter = None
    BaseSpeakerTTS = None

# For audio file handling
try:
    import soundfile as sf
    from scipy.io import wavfile
    AUDIO_LIBS_AVAILABLE = True
except ImportError:
    AUDIO_LIBS_AVAILABLE = False


class VoiceCloner:
    """OpenVoice V2 voice cloning for VAMP"""
    
    def __init__(self, model_dir: Optional[Path] = None, cache_dir: Optional[Path] = None):
        """
        Initialize the voice cloner
        
        Args:
            model_dir: Directory containing OpenVoice V2 models (checkpoint)
            cache_dir: Directory to cache voice embeddings and generated audio
        """
        if not OPENVOICE_AVAILABLE:
            error_msg = (
                "OpenVoice not installed.\n"
                "Install with:\n"
                "  pip install torch torchaudio soundfile scipy\n"
                "  pip install git+https://github.com/myshell-ai/OpenVoice.git\n\n"
                "On Windows, see VOICE_WINDOWS_SETUP.md for detailed instructions.\n"
            )
            if 'OPENVOICE_IMPORT_ERROR' in globals():
                error_msg += f"\nImport error: {OPENVOICE_IMPORT_ERROR}"
            raise RuntimeError(error_msg)
        
        if not AUDIO_LIBS_AVAILABLE:
            raise RuntimeError(
                "Audio libraries not installed. Install with: pip install soundfile scipy"
            )
        
        # Set up directories
        self.project_root = Path(__file__).resolve().parents[2]
        self.model_dir = model_dir or (self.project_root / "models" / "openvoice_v2")
        self.cache_dir = cache_dir or (self.project_root / "cache" / "voice")
        self.training_dir = self.project_root / "data" / "voice_samples"
        
        # Create directories
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.training_dir.mkdir(parents=True, exist_ok=True)
        
        # Device configuration
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"VoiceCloner initialized on device: {self.device}")
        
        # Model components (loaded lazily)
        self.base_speaker = None
        self.tone_converter = None
        self.target_se = None  # Speaker embedding for cloned voice
        self.is_trained = False
        
        # Voice configuration
        self.config_file = self.cache_dir / "voice_config.json"
        self.load_config()
    
    def load_config(self):
        """Load voice configuration if it exists"""
        if self.config_file.exists():
            with open(self.config_file, 'r') as f:
                self.config = json.load(f)
                self.is_trained = self.config.get('is_trained', False)
                print(f"Loaded voice config: trained={self.is_trained}")
        else:
            self.config = {
                'is_trained': False,
                'training_files': [],
                'last_trained': None
            }
    
    def save_config(self):
        """Save voice configuration"""
        with open(self.config_file, 'w') as f:
            json.dump(self.config, f, indent=2)

    def _build_reference_sample(
        self,
        voice_files: List[Path],
        voice_name: str,
        target_sr: int = 24000,
        max_seconds: float = 45.0,
    ) -> Path:
        """Create one strong reference WAV from multiple snippets for embedding extraction."""
        ranked = []
        for path in voice_files:
            try:
                audio, sr = sf.read(str(path), always_2d=False)
                if audio.ndim > 1:
                    audio = np.mean(audio, axis=1)
                audio = audio.astype(np.float32)
                if sr != target_sr:
                    gcd = int(np.gcd(sr, target_sr))
                    audio = signal.resample_poly(audio, target_sr // gcd, sr // gcd).astype(np.float32)
                if len(audio) == 0:
                    continue
                rms = float(np.sqrt(np.mean(np.square(audio))))
                duration = len(audio) / target_sr
                if duration >= 3.0 and rms > 0.002:
                    ranked.append((rms, duration, path, audio))
            except Exception as e:
                print(f"Skipping unusable voice sample {path}: {e}")

        if not ranked:
            raise ValueError("No usable voice snippets found for reference sample")

        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        silence = np.zeros(int(0.18 * target_sr), dtype=np.float32)
        chunks = []
        total = 0.0
        selected_files = []
        for _rms, duration, path, audio in ranked:
            if total >= max_seconds:
                break
            remaining = max_seconds - total
            take = audio[: int(min(duration, remaining) * target_sr)]
            if len(take) < int(2.0 * target_sr):
                continue
            peak = float(np.max(np.abs(take)) or 1.0)
            if peak > 0.98:
                take = take / peak * 0.96
            chunks.extend([take, silence])
            total += len(take) / target_sr
            selected_files.append(str(path))

        reference = np.concatenate(chunks).astype(np.float32)
        output = self.cache_dir / f"{voice_name}_reference.wav"
        sf.write(str(output), reference, target_sr, subtype="PCM_16")
        self.config["reference_files"] = selected_files
        self.config["reference_path"] = str(output)
        return output
    
    def _load_models(self):
        """Load OpenVoice models (lazy loading)"""
        if self.base_speaker is not None:
            return  # Already loaded
        
        print("Loading OpenVoice V2 models...")
        
        # Older OpenVoice bundles included a base speaker TTS checkpoint at
        # base_speakers/EN. OpenVoice V2 Hugging Face bundles often include
        # only tone-converter assets plus speaker embeddings; that is enough
        # for training/extracting the target speaker embedding.
        ckpt_base = self.model_dir / "base_speakers" / "EN"
        if (ckpt_base / "config.json").exists():
            self.base_speaker = BaseSpeakerTTS(str(ckpt_base / "config.json"), device=self.device)
            self.base_speaker.load_ckpt(str(ckpt_base / "checkpoint.pth"))
        else:
            self.base_speaker = None
            print(f"Base speaker TTS checkpoint not found at {ckpt_base}; converter-only mode enabled.")
        
        # Load tone color converter
        ckpt_converter = self.model_dir / "converter"
        self.tone_converter = ToneColorConverter(
            str(ckpt_converter / "config.json"),
            device=self.device,
        )
        self.tone_converter.load_ckpt(str(ckpt_converter / "checkpoint.pth"))
        
        print("Models loaded successfully")
    
    def train_voice(self, voice_files: List[Path], voice_name: str = "vamp_voice") -> Dict[str, Any]:
        """
        Train/extract voice embedding from provided voice samples
        
        Args:
            voice_files: List of audio file paths for training
            voice_name: Name for the voice profile
        
        Returns:
            Dictionary with training results and metadata
        """
        if not voice_files:
            raise ValueError("No voice files provided for training")
        
        print(f"Training voice from {len(voice_files)} samples...")
        
        # Load models if not already loaded
        self._load_models()
        
        # OpenVoice extracts one speaker embedding, so build one strong reference
        # from the best snippets instead of accidentally using only the first file.
        reference_speaker = str(self._build_reference_sample(voice_files, voice_name))
        
        try:
            # Extract tone color embedding directly. The higher-level
            # se_extractor path tries to segment with Whisper/CUDA, which is
            # unnecessary for our pre-cleaned combined reference sample.
            self.target_se = self.tone_converter.extract_se(reference_speaker)
            
            # Save the embedding
            embedding_path = self.cache_dir / f"{voice_name}_embedding.pt"
            torch.save(self.target_se, embedding_path)
            
            # Update config
            self.config['is_trained'] = True
            self.config['training_files'] = [str(f) for f in voice_files]
            self.config['last_trained'] = time.strftime("%Y-%m-%d %H:%M:%S")
            self.config['voice_name'] = voice_name
            self.config['embedding_path'] = str(embedding_path)
            self.is_trained = True
            self.save_config()
            
            print(f"✓ Voice trained successfully: {voice_name}")
            return {
                'success': True,
                'voice_name': voice_name,
                'samples_used': len(voice_files),
                'embedding_path': str(embedding_path),
                'trained_at': self.config['last_trained']
            }
            
        except Exception as e:
            print(f"✗ Voice training failed: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def load_trained_voice(self, voice_name: str = "vamp_voice") -> bool:
        """
        Load a previously trained voice embedding
        
        Args:
            voice_name: Name of the voice profile to load
        
        Returns:
            True if successfully loaded
        """
        embedding_path = self.cache_dir / f"{voice_name}_embedding.pt"
        
        if not embedding_path.exists():
            print(f"No trained voice found: {voice_name}")
            return False
        
        try:
            self._load_models()
            self.target_se = torch.load(embedding_path, map_location=self.device)
            self.is_trained = True
            print(f"✓ Loaded trained voice: {voice_name}")
            return True
        except Exception as e:
            print(f"✗ Failed to load voice: {e}")
            return False
    
    def text_to_speech(self, text: str, output_path: Optional[Path] = None) -> Optional[Path]:
        """
        Convert text to speech using the cloned voice
        
        Args:
            text: Text to convert to speech
            output_path: Optional path for output file (auto-generated if not provided)
        
        Returns:
            Path to generated audio file, or None if failed
        """
        if not self.is_trained:
            # Try to load default voice
            if not self.load_trained_voice():
                raise RuntimeError("No trained voice available. Please train a voice first.")
        
        # Load models if needed
        self._load_models()
        if self.base_speaker is None:
            raise RuntimeError(
                "OpenVoice converter is trained, but no local base speaker TTS checkpoint is installed. "
                "Install a compatible base TTS model or route generated base speech through the converter."
            )
        
        # Generate output path if not provided
        if output_path is None:
            # Create hash of text for caching
            text_hash = hashlib.md5(text.encode()).hexdigest()[:8]
            timestamp = int(time.time())
            output_path = self.cache_dir / f"speech_{timestamp}_{text_hash}.wav"
        
        try:
            # Generate base speech with neutral voice
            temp_base = self.cache_dir / f"temp_base_{int(time.time())}.wav"
            
            print(f"Generating speech for: {text[:50]}...")
            
            # Use base speaker to generate initial audio
            self.base_speaker.tts(text, str(temp_base), speaker='default', language='English', speed=1.0)
            
            # Convert tone color to match target voice
            encode_message = "@MyShell"  # Required by OpenVoice
            self.tone_converter.convert(
                audio_src_path=str(temp_base),
                src_se=None,  # Auto-extract from source
                tgt_se=self.target_se,
                output_path=str(output_path),
                message=encode_message
            )
            
            # Clean up temp file
            if temp_base.exists():
                temp_base.unlink()
            
            print(f"✓ Speech generated: {output_path.name}")
            return output_path
            
        except Exception as e:
            print(f"✗ Speech generation failed: {e}")
            return None
    
    def get_training_files(self) -> List[Path]:
        """Get list of available training files"""
        audio_extensions = ['.wav', '.mp3', '.flac', '.m4a', '.ogg']
        training_files = []
        
        for ext in audio_extensions:
            training_files.extend(self.training_dir.glob(f"*{ext}"))
        
        return sorted(training_files)
    
    def status(self) -> Dict[str, Any]:
        """Get current status of voice cloner"""
        return {
            'openvoice_available': OPENVOICE_AVAILABLE,
            'audio_libs_available': AUDIO_LIBS_AVAILABLE,
            'device': self.device,
            'models_loaded': self.base_speaker is not None,
            'is_trained': self.is_trained,
            'config': self.config,
            'training_files_available': len(self.get_training_files()),
            'model_dir': str(self.model_dir),
            'cache_dir': str(self.cache_dir),
            'training_dir': str(self.training_dir)
        }


# Singleton instance
_voice_cloner_instance: Optional[VoiceCloner] = None


def get_voice_cloner() -> VoiceCloner:
    """Get or create the singleton VoiceCloner instance"""
    global _voice_cloner_instance
    if _voice_cloner_instance is None:
        _voice_cloner_instance = VoiceCloner()
    return _voice_cloner_instance


def text_to_speech(text: str, output_path: Optional[Path] = None) -> Optional[Path]:
    """Convenience function for text-to-speech conversion"""
    try:
        cloner = get_voice_cloner()
        return cloner.text_to_speech(text, output_path)
    except Exception as e:
        print(f"TTS error: {e}")
        return None
